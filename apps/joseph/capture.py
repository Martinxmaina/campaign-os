"""Post-meeting capture surface logic (TB.4).

The capture loop closes the back half of a meeting. Three things live here, all
pure Django (the views in ``apps.joseph.views`` are thin wrappers over them):

- ``build_form_meeting`` — turns the quick-form's five fields (commitments /
  next step / due date / warmth delta / share toggle) into an
  ``ExtractedMeeting(source=form, status=pending)`` plus its ``ExtractedItem``
  children, **without** any transcription/extraction (the form is already
  structured input). The voice path instead persists a ``VoiceNote`` and
  enqueues the async pipeline (Task 5).
- ``send_capture_prompts`` — the beat-driven sweep (every 15 min) that prompts
  the owner of any meeting that ended within the last ``CAPTURE_WINDOW_MIN``
  minutes and still has ``capture_status == "none"`` (MEETING_CAPTURE), marking
  it ``prompted`` so a re-run is idempotent (it never double-prompts).
- ``escalate_deferred_captures`` — when a capture was deferred and is still
  uncaptured ``DEFER_ESCALATE_HOURS`` after the defer point, escalate to the
  thread's backstop (Nduta) so a deferred meeting never silently rots.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from apps.notifications.engine import notify
from apps.notifications.models import EventType

logger = logging.getLogger(__name__)

# A meeting that ended within this many minutes still gets a capture prompt.
CAPTURE_WINDOW_MIN = 180
# A deferred-then-still-uncaptured meeting is escalated this long after defer.
DEFER_ESCALATE_HOURS = 24
# A deferred capture re-prompts the owner this far out.
DEFER_HOURS = 2


def build_form_meeting(thread, *, commitments, next_step, due_date, warmth_delta, share, voice_note=None):
    """Persist a quick-form capture as a pending ``ExtractedMeeting`` + items.

    The five form fields map directly onto extracted items (no transcription):
    a non-empty ``commitments`` line becomes a ``commitment_follow_up`` item; a
    non-empty ``next_step`` becomes a ``next_step`` item carrying the parsed
    ``due_date`` as ``proposed_due``. ``warmth_delta`` is stored on the meeting
    (routed to a warmth rescore at confirm time, Task 6). ``share`` flags the
    note as shareable in the item payload so Task 6/7 can surface it.
    """
    from apps.joseph.models import ExtractedItem, ExtractedMeeting

    meeting = ExtractedMeeting.objects.create(
        thread=thread,
        voice_note=voice_note,
        source=ExtractedMeeting.Source.FORM,
        status=ExtractedMeeting.Status.PENDING,
        warmth_delta=warmth_delta if warmth_delta in ExtractedMeeting.WarmthDelta.values else "",
        relationship_notes=(commitments or "").strip(),
    )

    commitments = (commitments or "").strip()
    if commitments:
        ExtractedItem.objects.create(
            meeting=meeting,
            kind=ExtractedItem.Kind.COMMITMENT_FOLLOW_UP,
            description=commitments,
            confidence=1.0,  # the principal typed it — not an inference
            payload={"share": bool(share), "source": "form"},
        )

    next_step = (next_step or "").strip()
    if next_step:
        ExtractedItem.objects.create(
            meeting=meeting,
            kind=ExtractedItem.Kind.NEXT_STEP,
            description=next_step,
            confidence=1.0,
            proposed_due=_parse_date(due_date),
            payload={"share": bool(share), "source": "form"},
        )

    return meeting


def _parse_date(raw):
    """Parse an ``YYYY-MM-DD`` form value into a ``date`` (None when blank/bad)."""
    from django.utils.dateparse import parse_date

    if not raw:
        return None
    return parse_date(str(raw).strip())


def mark_captured(event) -> None:
    """Flip a CalendarEvent's capture state to ``captured`` (idempotent setter)."""
    if event is None:
        return
    if event.capture_status != "captured":
        event.capture_status = "captured"
        event.save(update_fields=["capture_status", "updated_at"])


def defer_capture(event):
    """Defer a meeting's capture: mark ``deferred`` + re-prompt in ``DEFER_HOURS``."""
    event.capture_status = "deferred"
    event.defer_until = timezone.now() + timedelta(hours=DEFER_HOURS)
    event.save(update_fields=["capture_status", "defer_until", "updated_at"])
    return event


def send_capture_prompts() -> dict:
    """Prompt the owner of every just-ended, uncaptured meeting (MEETING_CAPTURE).

    Walks linked CalendarEvents whose ``end`` fell within the last
    ``CAPTURE_WINDOW_MIN`` minutes and whose ``capture_status`` is still
    ``"none"``; notifies the thread owner (else a workspace principal) and marks
    the event ``prompted`` so a re-run never double-prompts. Returns a summary
    ``{prompted: n}``.
    """
    from apps.joseph.models import CalendarEvent

    now = timezone.now()
    window_start = now - timedelta(minutes=CAPTURE_WINDOW_MIN)
    qs = (
        CalendarEvent.objects.filter(
            capture_status="none",
            end__lte=now,
            end__gte=window_start,
        )
        .exclude(linked_thread_id="")
    )

    prompted = 0
    for event in qs:
        thread = _resolve_thread(event)
        if thread is None:
            continue
        user = getattr(thread, "owner", None) or _fallback_owner()
        if user is None:
            continue
        org = _org_name(thread)
        notify(
            user,
            EventType.MEETING_CAPTURE,
            f"Capture your meeting — {org}",
            f"How did the {org} meeting go? Capture the outcome while it's fresh.",
            data={
                "google_event_id": event.google_event_id,
                "thread_id": str(thread.id),
                "action": {"href": f"/joseph/capture/{thread.id}/"},
            },
        )
        event.capture_status = "prompted"
        event.save(update_fields=["capture_status", "updated_at"])
        prompted += 1

    return {"prompted": prompted}


def escalate_deferred_captures() -> dict:
    """Escalate a deferred-but-still-uncaptured meeting to the thread backstop.

    A capture deferred more than ``DEFER_ESCALATE_HOURS`` ago that is still in
    ``deferred`` state gets a MEETING_CAPTURE notification to the thread's
    backstop (Nduta) — the human-in-the-loop net so a deferred meeting is never
    silently lost. Idempotent via the ``escalated`` capture_status it leaves
    behind. Returns ``{escalated: n}``.
    """
    from apps.joseph.models import CalendarEvent

    cutoff = timezone.now() - timedelta(hours=DEFER_ESCALATE_HOURS)
    qs = (
        CalendarEvent.objects.filter(
            capture_status="deferred",
            defer_until__lte=cutoff,
        )
        .exclude(linked_thread_id="")
    )

    escalated = 0
    for event in qs:
        thread = _resolve_thread(event)
        if thread is None:
            continue
        backstop = getattr(thread, "backstop", None) or _fallback_owner()
        if backstop is None:
            continue
        org = _org_name(thread)
        notify(
            backstop,
            EventType.MEETING_CAPTURE,
            f"Uncaptured meeting needs a backstop — {org}",
            f"The {org} meeting was deferred over {DEFER_ESCALATE_HOURS}h ago and "
            "is still uncaptured. Please nudge or capture it.",
            data={
                "google_event_id": event.google_event_id,
                "thread_id": str(thread.id),
                "action": {"href": f"/joseph/capture/{thread.id}/"},
            },
        )
        event.capture_status = "escalated"
        event.save(update_fields=["capture_status", "updated_at"])
        escalated += 1

    return {"escalated": escalated}


# --------------------------------------------------------------------------
# helpers (mirror meeting_prep's thread/owner resolution)
# --------------------------------------------------------------------------


def _resolve_thread(event):
    """Load the linked CRM OutreachThread for ``event`` (None if gone/stale id)."""
    from django.core.exceptions import ValidationError

    from apps.crm.models import OutreachThread

    try:
        return (
            OutreachThread.objects.select_related("org", "owner", "backstop")
            .filter(pk=event.linked_thread_id)
            .first()
        )
    except (ValueError, ValidationError):
        return None


def _org_name(thread) -> str:
    return thread.org.name if getattr(thread, "org_id", None) else "this organisation"


def _fallback_owner():
    """A principal/owner/admin workspace member to receive a prompt when the
    thread itself has no owner (so a capture prompt never goes nowhere)."""
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
