"""Tests for the guarded outreach sender (``apps.outreach.senders``).

``guarded_send(mailbox, to, subject, body, thread, gate_id)`` is the single
adapter chokepoint where deliverability is enforced — *never* in views:

  1. suppression  — a ``SuppressionEntry`` for ``to`` raises ``AddressSuppressed``
     and the transport is NEVER called;
  2. cap / ramp   — at or above the mailbox's effective cap for today raises
     ``CapExceeded`` and the transport is NEVER called (ramp week is derived
     from ``(today - ramp_started_at).days // 7``);
  3. success      — appends the unsubscribe footer + sets the ``List-Unsubscribe``
     header, calls the Gmail sender, increments the per-day ``MailboxSend``,
     writes a ``crm.Activity(activity_type="email_sent")`` on the thread, and
     returns the transport's message id.

The pluggable senders: ``GmailEmailSender.send`` delegates to
``integrations.gmail.send_message`` (mocked here — no network); the
``InstantlyEmailSender`` is a stub seam that raises ``NotImplementedError``.
The gate stays authoritative upstream (Task 4) — ``guarded_send`` takes the
already-issued ``gate_id`` and records it on the Activity.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone


def _make_user(email="owner@waiis.test"):
    from apps.accounts.models import User

    return User.objects.create_user(
        email=email, password="x", name="Owner", tos_accepted_at=timezone.now()
    )


def _make_thread():
    from apps.crm.models import Contact, Organization, OutreachThread

    org = Organization.objects.create(name="Acme Capital")
    contact = Contact.objects.create(org=org, full_name="Pat Lee", email="pat@acme.org")
    return OutreachThread.objects.create(org=org, primary_contact=contact)


def _make_mailbox(email="joseph@africacen.org", **kwargs):
    from apps.outreach.models import Mailbox

    user = _make_user(f"u-{email}")
    return Mailbox.objects.create(user=user, email=email, **kwargs)


# ---------------------------------------------------------------------------
# Pluggable senders
# ---------------------------------------------------------------------------


def test_gmail_email_sender_delegates_to_send_message():
    """GmailEmailSender.send builds the service then calls integrations.gmail.send_message."""
    from apps.outreach.senders import GmailEmailSender

    sender = GmailEmailSender()
    service = MagicMock()
    integration = MagicMock()

    with patch("apps.outreach.senders.build_gmail_service", return_value=service) as build, patch(
        "apps.outreach.senders.send_message", return_value="m-99"
    ) as send:
        result = sender.send(
            integration,
            to="a@b.org",
            subject="s",
            body_html="<p>h</p>",
            sender="joseph@africacen.org",
            headers={"List-Unsubscribe": "<https://x/u/tok>"},
        )

    assert result == "m-99"
    build.assert_called_once_with(integration)
    send.assert_called_once()
    assert send.call_args.kwargs["to"] == "a@b.org"
    assert send.call_args.kwargs["headers"]["List-Unsubscribe"] == "<https://x/u/tok>"


def test_instantly_email_sender_is_a_stub():
    from apps.outreach.senders import InstantlyEmailSender

    with pytest.raises(NotImplementedError):
        InstantlyEmailSender().send(None, to="a@b.org", subject="s", body_html="<p>h</p>")


# ---------------------------------------------------------------------------
# guarded_send — suppression
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guarded_send_raises_on_suppressed_address_and_does_not_send():
    from apps.outreach.exceptions import AddressSuppressed
    from apps.outreach.models import SuppressionEntry
    from apps.outreach.senders import guarded_send

    mb = _make_mailbox()
    thread = _make_thread()
    SuppressionEntry.objects.create(email="blocked@acme.org", reason="unsubscribe")

    sender = MagicMock()
    with pytest.raises(AddressSuppressed):
        guarded_send(
            mb,
            to="blocked@acme.org",
            subject="hi",
            body="<p>hi</p>",
            thread=thread,
            gate_id="g-1",
            sender=sender,
        )

    sender.send.assert_not_called()


@pytest.mark.django_db
def test_guarded_send_suppression_is_case_insensitive():
    from apps.outreach.exceptions import AddressSuppressed
    from apps.outreach.models import SuppressionEntry
    from apps.outreach.senders import guarded_send

    mb = _make_mailbox()
    thread = _make_thread()
    SuppressionEntry.objects.create(email="blocked@acme.org")

    sender = MagicMock()
    with pytest.raises(AddressSuppressed):
        guarded_send(
            mb,
            to="Blocked@Acme.ORG",
            subject="hi",
            body="<p>hi</p>",
            thread=thread,
            gate_id="g-1",
            sender=sender,
        )
    sender.send.assert_not_called()


# ---------------------------------------------------------------------------
# guarded_send — cap / ramp
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guarded_send_raises_when_at_cap_and_does_not_send():
    from apps.outreach.exceptions import CapExceeded
    from apps.outreach.models import MailboxSend
    from apps.outreach.senders import guarded_send

    # week 2+ → effective cap is daily_cap (set low for the test)
    started = timezone.now() - timedelta(days=21)
    mb = _make_mailbox(daily_cap=5, ramp_started_at=started)
    thread = _make_thread()
    # already at the cap today
    MailboxSend.objects.create(mailbox=mb, date=timezone.localdate(), count=5)

    sender = MagicMock()
    with pytest.raises(CapExceeded):
        guarded_send(
            mb,
            to="pat@acme.org",
            subject="hi",
            body="<p>hi</p>",
            thread=thread,
            gate_id="g-1",
            sender=sender,
        )
    sender.send.assert_not_called()


@pytest.mark.django_db
def test_guarded_send_respects_warmup_ramp_week_zero():
    """Week 0 cap is 20 regardless of daily_cap; at 20 sends today must block."""
    from apps.outreach.exceptions import CapExceeded
    from apps.outreach.models import MailboxSend
    from apps.outreach.senders import guarded_send

    mb = _make_mailbox(daily_cap=50, ramp_started_at=timezone.now())  # week 0
    thread = _make_thread()
    MailboxSend.objects.create(mailbox=mb, date=timezone.localdate(), count=20)

    sender = MagicMock()
    with pytest.raises(CapExceeded):
        guarded_send(
            mb,
            to="pat@acme.org",
            subject="hi",
            body="<p>hi</p>",
            thread=thread,
            gate_id="g-1",
            sender=sender,
        )
    sender.send.assert_not_called()


# ---------------------------------------------------------------------------
# guarded_send — success path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guarded_send_success_injects_unsubscribe_sends_counts_and_logs_activity():
    from apps.crm.models import Activity
    from apps.outreach.models import MailboxSend
    from apps.outreach.senders import guarded_send

    started = timezone.now() - timedelta(days=21)  # week 2+ → full cap
    mb = _make_mailbox(daily_cap=50, ramp_started_at=started)
    thread = _make_thread()

    sender = MagicMock()
    sender.send.return_value = "m-success"

    result = guarded_send(
        mb,
        to="pat@acme.org",
        subject="Partnership at WAIIS",
        body="<p>Hello Pat</p>",
        thread=thread,
        gate_id="g-42",
        sender=sender,
    )

    assert result == "m-success"

    # transport called once with an unsubscribe footer appended + List-Unsubscribe header
    sender.send.assert_called_once()
    call = sender.send.call_args
    body_sent = call.kwargs["body_html"]
    assert "<p>Hello Pat</p>" in body_sent
    assert "unsubscribe" in body_sent.lower()
    assert "List-Unsubscribe" in call.kwargs["headers"]
    assert call.kwargs["to"] == "pat@acme.org"
    assert call.kwargs["subject"] == "Partnership at WAIIS"

    # per-day counter incremented to 1
    ms = MailboxSend.objects.get(mailbox=mb, date=timezone.localdate())
    assert ms.count == 1

    # an email_sent Activity is written on the thread, carrying the gate id + message id
    act = Activity.objects.get(thread=thread, activity_type="email_sent")
    assert act.content_ref.get("gate_id") == "g-42"
    assert act.content_ref.get("message_id") == "m-success"
    assert act.content_ref.get("to") == "pat@acme.org"


@pytest.mark.django_db
def test_guarded_send_increments_existing_counter():
    from apps.outreach.models import MailboxSend
    from apps.outreach.senders import guarded_send

    mb = _make_mailbox(daily_cap=50, ramp_started_at=timezone.now() - timedelta(days=21))
    thread = _make_thread()
    MailboxSend.objects.create(mailbox=mb, date=timezone.localdate(), count=3)

    sender = MagicMock()
    sender.send.return_value = "m-x"
    guarded_send(
        mb,
        to="pat@acme.org",
        subject="s",
        body="<p>b</p>",
        thread=thread,
        gate_id="g-1",
        sender=sender,
    )

    ms = MailboxSend.objects.get(mailbox=mb, date=timezone.localdate())
    assert ms.count == 4


@pytest.mark.django_db
def test_guarded_send_defaults_to_gmail_sender():
    """With no explicit sender, guarded_send uses GmailEmailSender (delegating to send_message)."""
    from apps.outreach.senders import guarded_send

    mb = _make_mailbox(daily_cap=50, ramp_started_at=timezone.now() - timedelta(days=21))
    thread = _make_thread()

    with patch("apps.outreach.senders.build_gmail_service", return_value=MagicMock()), patch(
        "apps.outreach.senders.send_message", return_value="m-default"
    ) as send:
        result = guarded_send(
            mb,
            to="pat@acme.org",
            subject="s",
            body="<p>b</p>",
            thread=thread,
            gate_id="g-1",
        )

    assert result == "m-default"
    send.assert_called_once()
