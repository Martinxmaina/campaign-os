"""Tests for gate-on-send (``apps.outreach.gating``) — the GATE INVARIANT.

Every outbound outreach email is gated *before* it can reach the transport.
The contract:

  * ``gate_or_block(body, track, author)`` submits the body to the existing
    agent-service content gate (the same gate ``apps/publisher`` uses). A
    ``pass`` verdict returns the issued ``gate_id``; a ``flag`` / ``block``
    verdict raises ``GateBlocked`` carrying the gate ``findings`` — the body is
    NEVER sent.

  * ``send_email(thread, subject, body, ...)`` is the high-level orchestrator:
    it runs ``gate_or_block`` first and only then calls ``guarded_send``. A
    blocked body must NOT reach the sender (the transport mock is asserted not
    called) and an approval-needed ``crm.Activity`` is queued so a human can
    review it.

All network (the gate client and the Gmail transport) is mocked — no real
calls, no real sends.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone


def _make_user(email="owner@waiis.test"):
    from apps.accounts.models import User

    return User.objects.create_user(
        email=email, password="x", name="Owner", tos_accepted_at=timezone.now()
    )


def _make_thread(track="energy"):
    from apps.crm.models import Contact, Organization, OutreachThread

    org = Organization.objects.create(name="Acme Capital")
    contact = Contact.objects.create(org=org, full_name="Pat Lee", email="pat@acme.org")
    return OutreachThread.objects.create(org=org, primary_contact=contact, track=track)


def _make_mailbox(email="joseph@africacen.org", **kwargs):
    from apps.outreach.models import Mailbox

    user = _make_user(f"u-{email}")
    kwargs.setdefault("daily_cap", 50)
    kwargs.setdefault("ramp_started_at", timezone.now() - timedelta(days=21))
    return Mailbox.objects.create(user=user, email=email, **kwargs)


# ---------------------------------------------------------------------------
# gate_or_block
# ---------------------------------------------------------------------------


def test_gate_or_block_pass_returns_gate_id():
    from apps.outreach.gating import gate_or_block

    with patch(
        "apps.outreach.gating.check_gate",
        return_value={"verdict": "pass", "findings": [], "gate_id": "g-77"},
    ) as check:
        gate_id = gate_or_block("<p>Hello Pat</p>", track="energy", author="joseph")

    assert gate_id == "g-77"
    check.assert_called_once()
    # the body + track + author are forwarded to the gate
    assert check.call_args.kwargs.get("track") == "energy" or "energy" in check.call_args.args
    assert check.call_args.kwargs.get("author") == "joseph" or "joseph" in check.call_args.args


def test_gate_or_block_flag_raises_gateblocked_with_findings():
    from apps.outreach.exceptions import GateBlocked
    from apps.outreach.gating import gate_or_block

    findings = [{"rule": "token_language", "match": "guaranteed returns"}]
    with patch(
        "apps.outreach.gating.check_gate",
        return_value={"verdict": "flag", "findings": findings, "gate_id": "g-1"},
    ):
        with pytest.raises(GateBlocked) as exc:
            gate_or_block("<p>guaranteed returns</p>", track="energy", author="joseph")

    assert exc.value.findings == findings


def test_gate_or_block_block_raises_gateblocked():
    from apps.outreach.exceptions import GateBlocked
    from apps.outreach.gating import gate_or_block

    findings = [{"rule": "confidential", "match": "internal-only"}]
    with patch(
        "apps.outreach.gating.check_gate",
        return_value={"verdict": "block", "findings": findings, "gate_id": "g-2"},
    ):
        with pytest.raises(GateBlocked) as exc:
            gate_or_block("<p>internal-only deck</p>", track="energy", author="joseph")

    assert exc.value.findings == findings


# ---------------------------------------------------------------------------
# send_email — pass path runs the guarded sender
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_send_email_pass_gates_then_guarded_sends():
    from apps.crm.models import Activity
    from apps.outreach.gating import send_email

    mb = _make_mailbox()
    thread = _make_thread()

    sender = MagicMock()
    sender.send.return_value = "m-ok"

    with patch(
        "apps.outreach.gating.check_gate",
        return_value={"verdict": "pass", "findings": [], "gate_id": "g-pass"},
    ):
        message_id = send_email(
            thread,
            subject="Partnership at WAIIS",
            body="<p>Hello Pat</p>",
            mailbox=mb,
            sender=sender,
        )

    assert message_id == "m-ok"
    # the gate verdict id rode through to the guarded sender → email_sent Activity
    sender.send.assert_called_once()
    act = Activity.objects.get(thread=thread, activity_type="email_sent")
    assert act.content_ref.get("gate_id") == "g-pass"
    assert act.content_ref.get("message_id") == "m-ok"


@pytest.mark.django_db
def test_send_email_forwards_thread_track_to_gate():
    from apps.outreach.gating import send_email

    mb = _make_mailbox()
    thread = _make_thread(track="ai10bn")
    sender = MagicMock()
    sender.send.return_value = "m-ok"

    with patch(
        "apps.outreach.gating.check_gate",
        return_value={"verdict": "pass", "findings": [], "gate_id": "g-pass"},
    ) as check:
        send_email(thread, subject="s", body="<p>b</p>", mailbox=mb, sender=sender)

    # track is taken from the thread when not passed explicitly
    passed_track = check.call_args.kwargs.get("track")
    assert passed_track == "ai10bn"


# ---------------------------------------------------------------------------
# send_email — block path NEVER reaches the transport + queues an approval
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_send_email_blocked_does_not_send_and_queues_approval():
    from apps.crm.models import Activity
    from apps.outreach.exceptions import GateBlocked
    from apps.outreach.gating import send_email

    mb = _make_mailbox()
    thread = _make_thread()

    sender = MagicMock()
    findings = [{"rule": "token_language", "match": "guaranteed returns"}]

    with patch(
        "apps.outreach.gating.check_gate",
        return_value={"verdict": "flag", "findings": findings, "gate_id": "g-blk"},
    ):
        with pytest.raises(GateBlocked):
            send_email(
                thread,
                subject="hi",
                body="<p>guaranteed returns</p>",
                mailbox=mb,
                sender=sender,
            )

    # GATE INVARIANT: a non-pass body never reaches the transport
    sender.send.assert_not_called()
    # no email_sent activity was written
    assert not Activity.objects.filter(thread=thread, activity_type="email_sent").exists()
    # an approval-needed activity is queued for human review, carrying the findings
    approval = Activity.objects.get(thread=thread, activity_type="email_gate_blocked")
    assert approval.content_ref.get("findings") == findings
    assert approval.content_ref.get("subject") == "hi"


@pytest.mark.django_db
def test_send_email_blocked_queues_approval_even_when_caller_swallows():
    """The approval Activity is written before the exception propagates, so it
    survives regardless of whether the caller re-raises or swallows."""
    from apps.crm.models import Activity
    from apps.outreach.exceptions import GateBlocked
    from apps.outreach.gating import send_email

    mb = _make_mailbox()
    thread = _make_thread()
    sender = MagicMock()

    with patch(
        "apps.outreach.gating.check_gate",
        return_value={"verdict": "block", "findings": [], "gate_id": "g-x"},
    ):
        try:
            send_email(thread, subject="s", body="<p>b</p>", mailbox=mb, sender=sender)
        except GateBlocked:
            pass

    assert Activity.objects.filter(thread=thread, activity_type="email_gate_blocked").exists()
    sender.send.assert_not_called()
