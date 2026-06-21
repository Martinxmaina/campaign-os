"""Routing for a confirmed meeting's extracted items (TB.4, Task 6).

The confirm screen lists an ``ExtractedMeeting``'s ``ExtractedItem`` lines with
accept/edit/dismiss. On confirm the view walks the items and hands each accepted
one to ``apply_item``, which switches on ``kind`` and routes it into the
canonical Django surfaces:

- ``commitment_*``   → Activity(commitment_recorded) **plus** a stage-proposal
  Task (``confirm_commitment``, owner=Joseph) surfaced to his queue — a captured
  commitment is recorded but the *stage advance* is a proposal he confirms, not
  an auto-advance.
- ``interest_expressed | objection_raised | strategy_signal`` → Activity(note)
  only — a relationship signal, no stage change, no task.
- ``next_step``      → Task (owner=Joseph, due=the proposed_due).
- ``intelligence_signal`` with ``wiki_update_candidate`` → a
  WikiRevisionCandidate(status=proposed) — surfaced for review, **never** auto-
  applied; without the flag it is a plain note.
- ``content_idea``   → ContentIntake(status=IDEA, submitted_by=Joseph), pillar
  pre-filled from the thread, sensitivity inferred from the track.

A dismissed item logs an Activity(note, "outcome logged") and routes nothing.
``apply_warmth`` folds the meeting's ``warmth_delta`` into ``thread.warmth`` and
triggers the same rescore the daily scorer runs. All routing is pure Django on
the canonical CRM/intake models — no agent-service call.
"""
from __future__ import annotations

import logging

from apps.content_intake.models import ContentIntake
from apps.crm.models import Activity, Task
from apps.crm.tasks import score_all_threads
from apps.joseph.models import ExtractedItem, WikiRevisionCandidate

logger = logging.getLogger(__name__)

# The commitment kinds — all route to Activity(commitment_recorded) + a Task.
_COMMITMENT_KINDS = {
    ExtractedItem.Kind.COMMITMENT_FINANCIAL,
    ExtractedItem.Kind.COMMITMENT_INTRO,
    ExtractedItem.Kind.COMMITMENT_FOLLOW_UP,
}

# Relationship signals — Activity(note) only, no stage change / task.
_NOTE_ONLY_KINDS = {
    ExtractedItem.Kind.INTEREST_EXPRESSED,
    ExtractedItem.Kind.OBJECTION_RAISED,
    ExtractedItem.Kind.STRATEGY_SIGNAL,
}

# Warmth ladder — a warmer/cooler delta steps the thread one rung along it.
_WARMTH_LADDER = ["cold", "warm", "hot"]

# Tracks whose meeting-derived content ideas are partner-sensitive by default
# (funder/deal-flow context). Anything outside this set is treated as public-safe.
# Fail-closed: an unknown/blank track lands on the partner-only rung, never public.
_PUBLIC_SAFE_TRACKS = {"core", "programs"}


def apply_item(item, *, by_user, workspace=None):
    """Route one accepted ``ExtractedItem`` into the canonical surfaces.

    ``by_user`` is the confirming principal (Joseph) — the owner/author of any
    Task/ContentIntake created. ``workspace`` is required to route a
    ``content_idea`` (ContentIntake is workspace-scoped); a content idea with no
    workspace falls back to a note so nothing is silently dropped. Marks the item
    ``accepted`` and returns the created object (or ``None``).
    """
    thread = item.meeting.thread
    kind = item.kind

    if kind in _COMMITMENT_KINDS:
        result = _route_commitment(item, thread, by_user)
    elif kind in _NOTE_ONLY_KINDS:
        result = _route_note(item, thread, summary=item.description)
    elif kind == ExtractedItem.Kind.NEXT_STEP:
        result = _route_next_step(item, thread, by_user)
    elif kind == ExtractedItem.Kind.INTELLIGENCE_SIGNAL:
        result = _route_intelligence(item, thread)
    elif kind == ExtractedItem.Kind.CONTENT_IDEA:
        result = _route_content_idea(item, thread, by_user, workspace)
    else:  # unknown kind — never silently drop it
        result = _route_note(item, thread, summary=item.description)

    item.state = ExtractedItem.State.ACCEPTED
    item.save(update_fields=["state", "updated_at"])
    return result


def dismiss_item(item):
    """Dismiss one item: log an "outcome logged" note and route nothing else."""
    note = _route_note(
        item, item.meeting.thread, summary=f"Meeting outcome logged (dismissed): {item.description}".strip()
    )
    item.state = ExtractedItem.State.DISMISSED
    item.save(update_fields=["state", "updated_at"])
    return note


def apply_warmth(meeting) -> bool:
    """Fold the meeting's ``warmth_delta`` into ``thread.warmth`` + rescore.

    Steps the thread one rung along the cold→warm→hot ladder (a "same" / blank
    delta is a no-op) and then triggers the same daily rescore so the score,
    quintile and traffic light reflect the new warmth. Returns True when the
    warmth actually changed.
    """
    delta = (meeting.warmth_delta or "").strip().lower()
    if delta not in ("warmer", "cooler"):
        return False

    thread = meeting.thread
    current = (thread.warmth or "cold").lower()
    if current not in _WARMTH_LADDER:
        current = "cold"
    idx = _WARMTH_LADDER.index(current)
    idx = min(idx + 1, len(_WARMTH_LADDER) - 1) if delta == "warmer" else max(idx - 1, 0)
    new = _WARMTH_LADDER[idx]
    if new == thread.warmth:
        return False
    thread.warmth = new
    thread.save(update_fields=["warmth", "updated_at"])
    # Re-run the canonical scorer so warmth flows into score/quintile/traffic.
    score_all_threads()
    return True


# --------------------------------------------------------------------------
# per-kind routers
# --------------------------------------------------------------------------


def _route_commitment(item, thread, by_user):
    """Record the commitment + surface a stage-proposal Task to Joseph's queue."""
    Activity.objects.create(
        thread=thread,
        activity_type="commitment_recorded",
        actor=by_user,
        content_ref={
            "kind": item.kind,
            "summary": item.description,
            "verbatim_quote": item.verbatim_quote,
            "confidence": item.confidence,
            "source": "meeting_capture",
        },
    )
    # The stage advance is a *proposal* Joseph confirms — never auto-advanced.
    return Task.objects.create(
        thread=thread,
        owner=by_user,
        type="confirm_commitment",
        status=Task.Status.OPEN,
        drafted_content=item.description,
    )


def _route_note(item, thread, *, summary):
    """Log a relationship/outcome note Activity (no stage change, no task)."""
    return Activity.objects.create(
        thread=thread,
        activity_type="note",
        actor=getattr(item, "_by_user", None),
        content_ref={
            "kind": item.kind,
            "summary": summary,
            "verbatim_quote": item.verbatim_quote,
            "source": "meeting_capture",
        },
    )


def _route_next_step(item, thread, by_user):
    """Open a follow-up Task (owner=Joseph, due=the proposed due date)."""
    return Task.objects.create(
        thread=thread,
        owner=by_user,
        type="next_step",
        status=Task.Status.OPEN,
        due=item.proposed_due,
        drafted_content=item.description,
    )


def _route_intelligence(item, thread):
    """A wiki-flagged signal → a *proposed* WikiRevisionCandidate (never applied);
    an unflagged one is just a note."""
    if not item.wiki_update_candidate:
        return _route_note(item, thread, summary=item.description)
    return WikiRevisionCandidate.objects.create(
        org=thread.org if thread.org_id else None,
        thread=thread,
        source_meeting=item.meeting,
        signal=item.description,
        proposed_change=item.description,
        status=WikiRevisionCandidate.Status.PROPOSED,
    )


def _route_content_idea(item, thread, by_user, workspace):
    """Drop a content idea into the intake board as an IDEA, pillar pre-filled
    from the thread, sensitivity inferred from the track. Falls back to a note
    when there is no workspace to scope the ContentIntake to."""
    if workspace is None:
        return _route_note(item, thread, summary=item.description)
    return ContentIntake.objects.create(
        workspace=workspace,
        external_id=f"meeting:{item.id}",
        submitted_by=by_user,
        owner=by_user,
        pillar_theme=thread.pillar or thread.track or "",
        angle=item.description,
        status=ContentIntake.Status.IDEA,
        sensitivity=_infer_sensitivity(thread),
        notes_raw=item.verbatim_quote,
    )


def _infer_sensitivity(thread) -> str:
    """Infer a ContentIntake sensitivity from the thread's track (fail-closed).

    A meeting-derived idea is partner-sensitive by default (it came out of a
    funder/deal conversation); only the clearly public-facing tracks
    (core programs) are marked public-safe.
    """
    track = (thread.track or "").strip().lower()
    if track in _PUBLIC_SAFE_TRACKS:
        return ContentIntake.Sensitivity.PUBLIC_SAFE
    return ContentIntake.Sensitivity.PARTNER_ONLY
