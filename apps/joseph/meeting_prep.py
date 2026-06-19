"""Pre-meeting cascade T-5 / T-2 / T-0 (TB.3).

``check_meeting_prep`` is the beat-driven sweep (``apps.joseph.tasks.run_meeting_prep``,
every 30 min) that walks every linked, future ``CalendarEvent`` and fires the
right stage for its days-to-start window, recording each fired stage in
``prep_stages`` so a re-run is idempotent (a stage never double-fires):

- **T-5** (≤5 days, >2): request a fresh dossier (``readers.compile_dossier`` —
  degrades to a no-op when agent-service is down) and notify the owner.
- **T-2** (≤2 days, >0): draft talking points (``talking_points.draft`` — 3
  bullets per track from the L0/dossier), run them through the status-language
  Pass-1 gate (``gate_talking_points``), store on ``event.talking_points``, and
  notify the owner with the L0 WHY-NOW summary.
- **T-0** (today): mark ``briefing_status="briefed"`` — the brief is ready for
  the "I'm going in" capture (Task 4).

A stage's window is "this stage or sooner": a meeting that is suddenly 2 days out
without a prior T-5 still fires T-5 then T-2 so nothing is skipped. Unlinked or
past events are ignored. The notification owner is the linked thread's owner; if
the thread has none we fall back to a workspace principal so the cascade never
goes nowhere.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.joseph import readers, talking_points
from apps.joseph.talking_points import gate_talking_points
from apps.notifications.engine import notify
from apps.notifications.models import EventType

logger = logging.getLogger(__name__)

# Days-to-start thresholds for each cascade stage (inclusive upper bound).
T5_WINDOW = 5
T2_WINDOW = 2


def check_meeting_prep() -> dict:
    """Fire the due cascade stage for every linked, future CalendarEvent.

    Returns a summary dict ``{fired: [...stage ids...], events: n}``. Idempotent
    via ``prep_stages`` — a stage already recorded on an event is skipped.
    """
    from apps.joseph.models import CalendarEvent

    now = timezone.now()
    today = timezone.localdate()
    fired: list[str] = []
    seen = 0

    # Today (T-0) or any future day — a meeting whose clock time already passed
    # earlier today still counts as "today" for the cascade, so we filter on the
    # calendar date, not the exact start instant.
    qs = (
        CalendarEvent.objects.filter(start__date__gte=today)
        .exclude(linked_thread_id="")
    )
    for event in qs:
        seen += 1
        # Whole calendar days to the meeting (0 == today, negative == past).
        days = (timezone.localtime(event.start).date() - today).days
        thread = _resolve_thread(event)
        if thread is None:
            continue

        stages = list(event.prep_stages or [])

        if days <= T5_WINDOW and "t5" not in stages:
            _fire_t5(event, thread)
            stages.append("t5")
            fired.append("t5")

        if days <= T2_WINDOW and "t2" not in stages:
            _fire_t2(event, thread)
            stages.append("t2")
            fired.append("t2")

        if days <= 0 and "t0" not in stages:
            _fire_t0(event)
            stages.append("t0")
            fired.append("t0")

        if stages != (event.prep_stages or []):
            event.prep_stages = stages
            event.save(update_fields=["prep_stages", "briefing_status", "talking_points", "updated_at"])

    return {"fired": fired, "events": seen}


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------


def _fire_t5(event, thread) -> None:
    """T-5 — request a dossier refresh + notify the owner."""
    readers.compile_dossier(str(thread.id))
    _notify(
        thread,
        title=f"Prep starting — {event.title}",
        body=f"Meeting in 5 days. Dossier refresh requested for {_org_name(thread)}.",
        data={"google_event_id": event.google_event_id, "stage": "t5"},
    )


def _fire_t2(event, thread) -> None:
    """T-2 — draft + gate talking points, store them, notify with the L0 summary."""
    points = talking_points.draft(thread)
    gated = gate_talking_points(points)
    event.talking_points = gated

    brief = _l0_brief(thread)
    why_now = (brief.get("why_now") or "").strip()
    summary = why_now or f"Talking points ready for {_org_name(thread)}."
    _notify(
        thread,
        title=f"Talking points ready — {event.title}",
        body=summary,
        data={
            "google_event_id": event.google_event_id,
            "stage": "t2",
            "talking_points": gated,
        },
    )


def _fire_t0(event) -> None:
    """T-0 — mark the brief ready for the 'I'm going in' capture."""
    event.briefing_status = "briefed"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _l0_brief(thread) -> dict:
    """Resolve the L0 brief for ``thread`` for the T-2 notification summary.

    Best-effort: a brief failure (agent-service hiccup) must never abort the
    cascade — the notification just falls back to a generic summary line.
    """
    from apps.joseph.intelligence import JosephIntelligence

    try:
        return JosephIntelligence().brief(thread) or {}
    except Exception as exc:  # brief must never abort the cascade
        logger.warning("meeting_prep: brief failed for thread %s: %s", getattr(thread, "id", "?"), exc)
        return {}


def _resolve_thread(event):
    """Load the linked CRM OutreachThread for ``event`` (None if it's gone).

    A non-UUID ``linked_thread_id`` (stale data) can't match the UUID pk; we
    tolerate the validation error and treat the event as unlinked.
    """
    from django.core.exceptions import ValidationError

    from apps.crm.models import OutreachThread

    try:
        return (
            OutreachThread.objects.select_related("org", "owner")
            .filter(pk=event.linked_thread_id)
            .first()
        )
    except (ValueError, ValidationError):
        return None


def _org_name(thread) -> str:
    return thread.org.name if getattr(thread, "org_id", None) else "this organisation"


def _notify(thread, *, title: str, body: str, data: dict) -> None:
    """Notify the cascade owner (thread owner, else a workspace principal)."""
    user = getattr(thread, "owner", None)
    if user is None:
        user = _fallback_owner()
    if user is None:
        return
    notify(user, EventType.MEETING_PREP, title, body, data=data)


def _fallback_owner():
    """A principal/owner/admin workspace member to receive a cascade notification
    when the thread itself has no owner (so the prep never goes nowhere)."""
    from apps.members.models import WorkspaceMembership

    m = (
        WorkspaceMembership.objects.filter(
            workspace_role__in=("owner", "admin", "principal"),
            user__is_active=True,
        )
        .select_related("user")
        .first()
    )
    return m.user if m else None
