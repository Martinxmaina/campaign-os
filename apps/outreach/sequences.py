"""Multi-step outreach sequences — ``enroll`` + ``advance``.

A :class:`~apps.outreach.models.SequenceTemplate` is a reusable plan of steps.
``enroll(thread, template)`` materialises a live :class:`Sequence` for the thread
with one :class:`SequenceStep` per template step, scheduling each step at
``now + cumulative delay_days``.

``advance(now)`` is the daily sweep (driven by the ``outreach-advance`` beat). It
resolves every *due* (``scheduled_for <= now``) pending step on an active
sequence:

  * **email** steps go through the gated :func:`apps.outreach.gating.send_email`
    orchestrator — the GATE INVARIANT holds: a non-pass body raises ``GateBlocked``
    inside ``send_email`` and never reaches the transport. A sent step is marked
    ``sent``.
  * **human-channel** steps (linkedin / whatsapp / call) are *never* auto-sent —
    ``advance`` opens a :class:`crm.Task` for the thread owner and marks the step
    ``task_open``.

A future step is left untouched. Once every step of a sequence is resolved (no
pending steps remain) the sequence is marked ``completed``.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.outreach.gating import send_email
from apps.outreach.models import HUMAN_CHANNELS, Sequence, SequenceStep

logger = logging.getLogger(__name__)


def enroll(thread, template) -> Sequence:
    """Create a :class:`Sequence` for ``thread`` from ``template``.

    One :class:`SequenceStep` per template step, with ``scheduled_for`` = now +
    the cumulative sum of ``delay_days`` (so step 1 fires immediately if its
    delay is 0, step 2 after step-1's + step-2's delay, etc.). Returns the
    created (active) sequence.
    """
    now = timezone.now()
    seq = Sequence.objects.create(template=template, thread=thread)

    cumulative_days = 0
    for position, step in enumerate(template.steps or [], start=1):
        cumulative_days += int(step.get("delay_days", 0) or 0)
        SequenceStep.objects.create(
            sequence=seq,
            position=position,
            kind=(step.get("kind") or "email"),
            subject=step.get("subject", "") or "",
            body=step.get("body", "") or "",
            delay_days=int(step.get("delay_days", 0) or 0),
            scheduled_for=now + timezone.timedelta(days=cumulative_days),
        )
    return seq


def _resolve_mailbox(thread):
    """The active sending mailbox for a thread — its owner's mailbox.

    Returns ``None`` if the owner has no active mailbox; the caller then leaves
    the email step pending (it will retry on the next sweep once a mailbox is
    connected) rather than crashing the whole sweep.
    """
    from apps.outreach.models import Mailbox

    owner_id = getattr(thread, "owner_id", None)
    if not owner_id:
        return None
    return (
        Mailbox.objects.filter(user_id=owner_id, status=Mailbox.Status.ACTIVE)
        .order_by("created_at")
        .first()
    )


def _open_human_task(step, thread) -> bool:
    """Open a ``crm.Task`` for a due human-channel step. Returns True on success."""
    from apps.crm.models import Task

    owner_id = getattr(thread, "owner_id", None)
    if not owner_id:
        # No owner to assign — leave the step pending for a later sweep.
        return False

    Task.objects.create(
        thread=thread,
        owner_id=owner_id,
        type=f"outreach_{step.kind}",
        drafted_content=step.body or "",
    )
    step.status = SequenceStep.Status.TASK_OPEN
    step.save(update_fields=["status", "updated_at"])
    return True


def _send_email_step(step, thread) -> bool:
    """Gate + send a due email step. Returns True on success.

    Delegates to the gated ``send_email`` orchestrator (gate-on-send is enforced
    there). A missing mailbox or a ``GateBlocked`` leaves the step pending so the
    sweep is resilient and never bypasses the gate.
    """
    from apps.outreach.exceptions import GateBlocked, OutreachError

    mailbox = _resolve_mailbox(thread)
    if mailbox is None:
        logger.info("outreach.advance step=%s no active mailbox; left pending", step.id)
        return False

    try:
        message_id = send_email(
            thread,
            subject=step.subject or "Follow-up",
            body=step.body,
            mailbox=mailbox,
        )
    except GateBlocked:
        # send_email already queued an approval Activity; leave the step pending.
        logger.info("outreach.advance step=%s gate-blocked; approval queued", step.id)
        return False
    except OutreachError as exc:
        # Suppression / cap — deliverability guard tripped; leave pending.
        logger.info("outreach.advance step=%s deliverability blocked: %s", step.id, exc)
        return False

    step.status = SequenceStep.Status.SENT
    step.message_id = message_id or ""
    step.save(update_fields=["status", "message_id", "updated_at"])
    return True


def advance(*, now=None) -> dict:
    """Resolve all due steps across active sequences. Returns ``{sent, tasks}``.

    Email steps are gated+sent; human-channel steps open owner tasks; future
    steps are untouched; a sequence with no remaining pending steps is completed.
    """
    if now is None:
        now = timezone.now()

    sent = 0
    tasks = 0

    due_steps = (
        SequenceStep.objects.select_related("sequence", "sequence__thread")
        .filter(
            status=SequenceStep.Status.PENDING,
            scheduled_for__lte=now,
            sequence__status=Sequence.Status.ACTIVE,
        )
        .order_by("scheduled_for", "position")
    )

    touched_sequences = set()
    for step in due_steps:
        thread = step.sequence.thread
        if step.kind in HUMAN_CHANNELS:
            if _open_human_task(step, thread):
                tasks += 1
                touched_sequences.add(step.sequence_id)
        else:
            if _send_email_step(step, thread):
                sent += 1
                touched_sequences.add(step.sequence_id)

    # Complete any active sequence that has no pending steps left.
    completed = 0
    active = Sequence.objects.filter(status=Sequence.Status.ACTIVE)
    for seq in active:
        if not seq.steps.filter(status=SequenceStep.Status.PENDING).exists():
            seq.status = Sequence.Status.COMPLETED
            seq.save(update_fields=["status", "updated_at"])
            completed += 1

    logger.info("outreach.advance sent=%s tasks=%s completed=%s", sent, tasks, completed)
    return {"sent": sent, "tasks": tasks, "completed": completed}
