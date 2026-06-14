"""Gate-on-send — the GATE INVARIANT for outreach.

Every outbound outreach email passes through the agent-service content gate
*before* it can reach a transport. This module owns that chokepoint:

  * ``gate_or_block(body, track, author)`` submits the body to the gate (the
    same gate ``apps/publisher`` uses, via ``publisher.gate_client.check_gate``).
    A ``pass`` verdict returns the issued ``gate_id``; any other verdict
    (``flag`` / ``block`` — and a missing/unknown verdict, which fails closed)
    raises :class:`GateBlocked` carrying the gate ``findings``. The body is
    NEVER sent.

  * ``send_email(thread, subject, body, ...)`` is the high-level orchestrator
    that gates first and only then delegates to the deliverability adapter
    ``guarded_send``. On a block it records an approval-needed
    ``crm.Activity(activity_type="email_gate_blocked")`` so a human can review,
    *before* re-raising — and the transport is never touched.

The gate verdict id is recorded on the ``email_sent`` Activity (written inside
``guarded_send``), so every send is auditable back to the gate that cleared it.
"""
from __future__ import annotations

from apps.outreach.exceptions import GateBlocked
from apps.outreach.senders import EmailSender, guarded_send
from apps.publisher.gate_client import check_gate

# Only a true ``pass`` clears the body for sending. Everything else — ``flag``,
# ``block``, or an unexpected/absent verdict — is treated as blocked (fail
# closed), so a misbehaving gate can never silently let a body through.
_PASS = "pass"


def gate_or_block(body: str, *, track: str | None = None, author: str | None = None) -> str:
    """Gate ``body``; return the issued ``gate_id`` on pass, else raise.

    Raises :class:`GateBlocked` (carrying the gate findings) for any non-pass
    verdict. The caller must treat the returned ``gate_id`` as the authoritative
    clearance to send.
    """
    result = check_gate(body, track=track, author=author)
    verdict = result.get("verdict")
    if verdict != _PASS:
        raise GateBlocked(
            f"gate verdict {verdict!r}",
            findings=result.get("findings") or [],
        )
    return result.get("gate_id")


def send_email(
    thread,
    *,
    subject: str,
    body: str,
    mailbox,
    to: str | None = None,
    track: str | None = None,
    author: str | None = None,
    sender: EmailSender | None = None,
    extra_headers: dict | None = None,
) -> str:
    """Gate then send one outbound email on ``thread``.

    1. ``gate_or_block`` — a non-pass body raises :class:`GateBlocked`; an
       approval-needed Activity is queued and the transport is never reached.
    2. ``guarded_send`` — deliverability guards (suppression → cap/ramp →
       unsubscribe injection → send → count → ``email_sent`` Activity).

    ``to`` defaults to the thread's primary contact email; ``track`` defaults to
    the thread's track. Returns the transport message id.
    """
    if track is None:
        track = getattr(thread, "track", "") or None

    try:
        gate_id = gate_or_block(body, track=track, author=author)
    except GateBlocked as exc:
        _queue_gate_approval(thread, subject=subject, body=body, findings=exc.findings)
        raise

    recipient = to
    if recipient is None:
        contact = getattr(thread, "primary_contact", None)
        recipient = getattr(contact, "email", "") if contact else ""

    return guarded_send(
        mailbox,
        to=recipient,
        subject=subject,
        body=body,
        thread=thread,
        gate_id=gate_id,
        sender=sender,
        extra_headers=extra_headers,
    )


def _queue_gate_approval(thread, *, subject: str, body: str, findings) -> None:
    """Record an approval-needed Activity for a gate-blocked outbound email.

    Written *before* :class:`GateBlocked` propagates so the review item survives
    whether the caller re-raises or swallows. The transport is never touched.
    """
    from apps.crm.models import Activity

    Activity.objects.create(
        thread=thread,
        activity_type="email_gate_blocked",
        actor_type="agent",
        agent_name="outreach",
        content_ref={
            "subject": subject,
            "body": body,
            "findings": findings or [],
            "needs_approval": True,
        },
    )
