"""No-reply follow-ups + inbound reply-triage for the outreach engine.

Two complementary halves:

  * :func:`triage_inbound` runs on the messages a Gmail sync just fetched. It
    matches each inbound message to a CRM thread — by ``In-Reply-To`` against a
    *sent* :class:`~apps.outreach.models.SequenceStep` first (the strongest link),
    else by the ``From`` address against a :class:`~apps.crm.models.Contact`'s
    email. A match:

      1. writes a ``crm.Activity(activity_type="email_reply")`` on the thread,
      2. **pauses** the thread's active sequence(s) — a human is now in the loop,
         so the automated cadence must stop,
      3. stamps ``last_touch`` / ``last_touch_channel="email"`` on the thread, and
      4. emits a reply-triage notification for the owner.

    An *unmatched* message is counted as general-inbox review and never touches a
    thread (no sequence is paused, no activity written).

  * :func:`run_no_reply` is the daily follow-up sweep. For each active thread whose
    latest sent email step has gone unanswered for ``NO_REPLY_AMBER_DAYS`` days (no
    ``email_reply`` Activity since the send) it drafts a follow-up: opens a
    ``crm.Task`` for the owner and flips ``traffic_light`` amber (>=N) / red (>=2N).
    A thread that already replied stays green.

This module never sends — the GATE INVARIANT is upheld upstream: the drafted
follow-up Task carries the body for the owner to send through the gated
``send_email`` chokepoint (or to enroll a follow-up sequence). The only network
here is the reply-triage notification, which degrades gracefully.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.joseph.readers import create_notification

logger = logging.getLogger(__name__)

# Days since the last unanswered send before a thread is flagged. Mirrors the
# CRM no-reply thresholds (amber >= N, red >= 2N) so the surfaces agree.
NO_REPLY_AMBER_DAYS = 14
NO_REPLY_RED_DAYS = 28


def _parse_email(raw: str) -> str:
    """Extract the bare address from a ``From`` header.

    ``"Pat Lee <pat@acme.org>"`` -> ``"pat@acme.org"``; a bare ``"pat@acme.org"``
    is returned unchanged. Lower-cased for case-insensitive matching.
    """
    from email.utils import parseaddr

    _name, addr = parseaddr(str(raw or ""))
    return (addr or raw or "").strip().lower()


def _match_thread(msg: dict):
    """Resolve the CRM thread an inbound message belongs to, or ``None``.

    ``In-Reply-To`` against a *sent* ``SequenceStep.message_id`` is tried first
    (the strongest signal — it links a reply directly to the email we sent); the
    ``From`` address against a ``Contact.email`` is the fallback.
    """
    from apps.crm.models import OutreachThread
    from apps.outreach.models import SequenceStep

    in_reply_to = (msg.get("in_reply_to") or msg.get("In-Reply-To") or "").strip()
    if in_reply_to:
        step = (
            SequenceStep.objects.filter(
                status=SequenceStep.Status.SENT, message_id=in_reply_to
            )
            .select_related("sequence", "sequence__thread")
            .first()
        )
        if step is not None:
            return step.sequence.thread

    sender = _parse_email(msg.get("from") or msg.get("From") or "")
    if sender:
        return (
            OutreachThread.objects.filter(primary_contact__email__iexact=sender)
            .order_by("-created_at")
            .first()
        )
    return None


def _pause_active_sequences(thread) -> int:
    """Pause every active sequence on ``thread``; return how many were paused."""
    from apps.outreach.models import Sequence

    return Sequence.objects.filter(
        thread=thread, status=Sequence.Status.ACTIVE
    ).update(status=Sequence.Status.PAUSED, updated_at=timezone.now())


def triage_inbound(messages) -> dict:
    """Triage a batch of inbound Gmail messages. Returns ``{matched, unmatched, paused}``.

    A matched message records an ``email_reply`` Activity, pauses the thread's
    active sequence(s), stamps ``last_touch``, and fires a reply-triage
    notification. An unmatched message is left for general inbox review.
    """
    from apps.crm.models import Activity

    matched = 0
    unmatched = 0
    paused = 0

    for msg in messages or []:
        thread = _match_thread(msg)
        if thread is None:
            unmatched += 1
            continue

        Activity.objects.create(
            thread=thread,
            activity_type="email_reply",
            actor_type="agent",
            agent_name="outreach",
            content_ref={
                "from": msg.get("from") or msg.get("From") or "",
                "subject": msg.get("subject") or msg.get("Subject") or "",
                "snippet": msg.get("snippet") or "",
                "message_id": msg.get("id") or "",
            },
        )

        paused += _pause_active_sequences(thread)

        thread.last_touch = timezone.now()
        thread.last_touch_channel = "email"
        thread.save(update_fields=["last_touch", "last_touch_channel", "updated_at"])

        _notify_reply(thread, msg)
        matched += 1

    logger.info(
        "outreach.triage_inbound matched=%s unmatched=%s paused=%s",
        matched, unmatched, paused,
    )
    return {"matched": matched, "unmatched": unmatched, "paused": paused}


def _notify_reply(thread, msg) -> None:
    """Fire a reply-triage notification for a matched inbound reply (best-effort)."""
    create_notification(
        "outreach_reply",
        f"Reply on “{thread.org.name}” — {msg.get('subject') or '(no subject)'}",
        thread_id=str(thread.id),
        action={"href": f"/joseph/thread/{thread.id}/"},
    )


def _last_sent_step(thread):
    """The most-recent *sent* email step on ``thread`` (across its sequences), or None."""
    from apps.outreach.models import SequenceStep

    return (
        SequenceStep.objects.filter(
            sequence__thread=thread, status=SequenceStep.Status.SENT, kind="email"
        )
        .order_by("-created_at")
        .first()
    )


def _has_reply_since(thread, when) -> bool:
    """True if an ``email_reply`` Activity exists on ``thread`` at/after ``when``."""
    from apps.crm.models import Activity

    return Activity.objects.filter(
        thread=thread, activity_type="email_reply", created_at__gte=when
    ).exists()


def run_no_reply(*, now=None) -> dict:
    """Daily sweep: draft follow-ups for unanswered sent steps. ``{amber, red}``.

    For each active thread whose latest sent email step has gone unanswered for
    ``NO_REPLY_AMBER_DAYS`` (no ``email_reply`` since the send) we draft a
    follow-up: open a ``crm.Task`` for the owner and flip ``traffic_light`` amber
    (>=N) / red (>=2N). The follow-up is never auto-sent — the owner sends it
    through the gated chokepoint.
    """
    from apps.crm.models import OutreachThread, Task

    if now is None:
        now = timezone.now()

    amber = 0
    red = 0

    # Only threads that actually have a sent step are candidates; closed threads
    # are out of scope (terminal — no nagging).
    closed = {OutreachThread.Stage.CONTRACTED, OutreachThread.Stage.CLOSED}
    threads = (
        OutreachThread.objects.exclude(stage__in=closed)
        .filter(sequences__steps__status="sent", sequences__steps__kind="email")
        .distinct()
    )

    for thread in threads:
        step = _last_sent_step(thread)
        if step is None:
            continue
        sent_at = step.created_at
        if _has_reply_since(thread, sent_at):
            continue

        age = (now - sent_at).days
        if age >= NO_REPLY_RED_DAYS:
            level = "red"
        elif age >= NO_REPLY_AMBER_DAYS:
            level = "amber"
        else:
            continue

        if thread.traffic_light != level:
            thread.traffic_light = level
            if not thread.next_action:
                thread.next_action = (
                    f"Owner: send gate-checked follow-up (no reply {age}d)"
                )
            thread.save(update_fields=["traffic_light", "next_action", "updated_at"])

        # Draft a follow-up Task for the owner (idempotent: skip if one is open).
        if thread.owner_id and not Task.objects.filter(
            thread=thread, type="outreach_followup", status=Task.Status.OPEN
        ).exists():
            Task.objects.create(
                thread=thread,
                owner_id=thread.owner_id,
                type="outreach_followup",
                drafted_content=(step.body or ""),
            )

        if level == "red":
            red += 1
        else:
            amber += 1

    logger.info("outreach.run_no_reply amber=%s red=%s", amber, red)
    return {"amber": amber, "red": red}
