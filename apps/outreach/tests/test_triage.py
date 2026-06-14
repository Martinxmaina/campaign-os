"""Tests for no-reply follow-ups + inbound reply-triage (``apps.outreach.triage``).

Two halves:

  * ``triage_inbound(messages)`` matches each inbound Gmail message to a thread —
    by ``In-Reply-To`` against a sent ``SequenceStep.message_id`` first, else by the
    ``From`` address against a ``Contact.email``. A match creates a
    ``crm.Activity(activity_type="email_reply")``, **pauses** the thread's active
    sequence(s), stamps ``last_touch``, and emits a reply-triage notification. An
    *unmatched* message is counted as general-inbox review and never touches a
    thread.

  * ``run_no_reply()`` finds threads whose latest sent step has gone unanswered for
    N days (no ``email_reply`` since the send) and drafts a follow-up — opening a
    ``crm.Task`` for the owner and flipping ``traffic_light`` amber (>=N) / red
    (>=2N). A thread that already got a reply is left green.

All network (notifications) is mocked — no real calls.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _make_user(email="owner@waiis.test"):
    from apps.accounts.models import User

    return User.objects.create_user(
        email=email, password="x", name="Owner", tos_accepted_at=timezone.now()
    )


def _make_thread(owner=None, contact_email="pat@acme.org", track="energy"):
    from apps.crm.models import Contact, Organization, OutreachThread

    org = Organization.objects.create(name="Acme Capital")
    contact = Contact.objects.create(org=org, full_name="Pat Lee", email=contact_email)
    if owner is None:
        owner = _make_user("thread-owner@waiis.test")
    return OutreachThread.objects.create(
        org=org, primary_contact=contact, track=track, owner=owner
    )


def _make_active_sequence(thread, *, sent_message_id="", sent_at=None):
    """A thread with one active sequence; optionally one already-sent step."""
    from apps.outreach.models import Sequence, SequenceStep

    seq = Sequence.objects.create(thread=thread, status=Sequence.Status.ACTIVE)
    if sent_message_id:
        step = SequenceStep.objects.create(
            sequence=seq,
            position=1,
            kind="email",
            subject="Intro",
            body="<p>Hi</p>",
            delay_days=0,
            scheduled_for=sent_at or timezone.now(),
            status=SequenceStep.Status.SENT,
            message_id=sent_message_id,
        )
        if sent_at:
            # auto_now_add stamps created_at to now(); push it back for no-reply tests
            SequenceStep.objects.filter(pk=step.pk).update(created_at=sent_at)
    return seq


# ---------------------------------------------------------------------------
# triage_inbound — match by Contact.email
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_triage_inbound_matches_by_contact_email_creates_reply_activity_and_pauses():
    from apps.crm.models import Activity
    from apps.outreach.models import Sequence
    from apps.outreach.triage import triage_inbound

    thread = _make_thread(contact_email="pat@acme.org")
    seq = _make_active_sequence(thread)

    messages = [
        {
            "id": "m-100",
            "from": "Pat Lee <pat@acme.org>",
            "subject": "Re: Intro",
            "snippet": "Thanks for reaching out!",
        }
    ]

    with patch("apps.outreach.triage.create_notification") as notify:
        result = triage_inbound(messages)

    # an email_reply Activity was written on the matched thread
    reply = Activity.objects.get(thread=thread, activity_type="email_reply")
    assert reply.content_ref.get("from") == "Pat Lee <pat@acme.org>"
    assert reply.content_ref.get("message_id") == "m-100"

    # the active sequence is paused (a human is now in the loop)
    assert Sequence.objects.get(pk=seq.pk).status == Sequence.Status.PAUSED

    # a reply-triage notification fired for the owner
    notify.assert_called_once()

    assert result.get("matched") == 1
    assert result.get("unmatched") == 0
    assert result.get("paused") == 1


# ---------------------------------------------------------------------------
# triage_inbound — match by In-Reply-To against a sent step (preferred)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_triage_inbound_matches_by_in_reply_to_sent_step():
    from apps.crm.models import Activity
    from apps.outreach.triage import triage_inbound

    # contact email deliberately does NOT match the From; only In-Reply-To links it.
    thread = _make_thread(contact_email="someone-else@acme.org")
    _make_active_sequence(thread, sent_message_id="<sent-abc>")

    messages = [
        {
            "id": "m-200",
            "from": "assistant@acme.org",
            "subject": "Re: Intro",
            "in_reply_to": "<sent-abc>",
            "snippet": "Forwarding on behalf of Pat.",
        }
    ]

    with patch("apps.outreach.triage.create_notification"):
        result = triage_inbound(messages)

    assert Activity.objects.filter(thread=thread, activity_type="email_reply").exists()
    assert result.get("matched") == 1


# ---------------------------------------------------------------------------
# triage_inbound — unmatched → general inbox review, no thread touched
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_triage_inbound_unmatched_message_touches_nothing():
    from apps.crm.models import Activity
    from apps.outreach.triage import triage_inbound

    thread = _make_thread(contact_email="pat@acme.org")
    seq = _make_active_sequence(thread)

    messages = [
        {
            "id": "m-300",
            "from": "stranger@nowhere.org",
            "subject": "Cold pitch",
            "snippet": "Buy my SaaS",
        }
    ]

    with patch("apps.outreach.triage.create_notification") as notify:
        result = triage_inbound(messages)

    # no thread touched: no reply activity, sequence stays active, no notify
    assert not Activity.objects.filter(activity_type="email_reply").exists()
    from apps.outreach.models import Sequence

    assert Sequence.objects.get(pk=seq.pk).status == Sequence.Status.ACTIVE
    notify.assert_not_called()

    assert result.get("matched") == 0
    assert result.get("unmatched") == 1
    assert result.get("paused") == 0


# ---------------------------------------------------------------------------
# triage_inbound — stamps last_touch on the matched thread
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_triage_inbound_stamps_last_touch():
    from apps.crm.models import OutreachThread
    from apps.outreach.triage import triage_inbound

    thread = _make_thread(contact_email="pat@acme.org")
    assert thread.last_touch is None

    with patch("apps.outreach.triage.create_notification"):
        triage_inbound([{"id": "m-400", "from": "pat@acme.org", "subject": "Re"}])

    refreshed = OutreachThread.objects.get(pk=thread.pk)
    assert refreshed.last_touch is not None
    assert refreshed.last_touch_channel == "email"


# ---------------------------------------------------------------------------
# run_no_reply — sent step, no reply after N days → follow-up + amber/red
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_run_no_reply_amber_after_threshold_drafts_followup():
    from apps.crm.models import OutreachThread, Task
    from apps.outreach.triage import NO_REPLY_AMBER_DAYS, run_no_reply

    owner = _make_user("nr-owner@waiis.test")
    thread = _make_thread(owner=owner)
    sent_at = timezone.now() - timedelta(days=NO_REPLY_AMBER_DAYS + 1)
    _make_active_sequence(thread, sent_message_id="<s1>", sent_at=sent_at)

    result = run_no_reply(now=timezone.now())

    refreshed = OutreachThread.objects.get(pk=thread.pk)
    assert refreshed.traffic_light == "amber"
    # a follow-up task was drafted for the owner
    task = Task.objects.get(thread=thread)
    assert task.owner_id == owner.id
    assert "follow" in task.type.lower() or "no_reply" in task.type.lower()
    assert result.get("amber") == 1


@pytest.mark.django_db
def test_run_no_reply_red_after_double_threshold():
    from apps.crm.models import OutreachThread
    from apps.outreach.triage import NO_REPLY_RED_DAYS, run_no_reply

    thread = _make_thread()
    sent_at = timezone.now() - timedelta(days=NO_REPLY_RED_DAYS + 1)
    _make_active_sequence(thread, sent_message_id="<s2>", sent_at=sent_at)

    result = run_no_reply(now=timezone.now())

    assert OutreachThread.objects.get(pk=thread.pk).traffic_light == "red"
    assert result.get("red") == 1


@pytest.mark.django_db
def test_run_no_reply_leaves_replied_thread_green():
    from apps.crm.models import Activity, OutreachThread
    from apps.outreach.triage import NO_REPLY_AMBER_DAYS, run_no_reply

    thread = _make_thread()
    sent_at = timezone.now() - timedelta(days=NO_REPLY_AMBER_DAYS + 5)
    _make_active_sequence(thread, sent_message_id="<s3>", sent_at=sent_at)
    # a reply landed *after* the send → no follow-up nag
    Activity.objects.create(
        thread=thread, activity_type="email_reply", actor_type="agent",
        agent_name="outreach", content_ref={"message_id": "r-1"},
    )

    result = run_no_reply(now=timezone.now())

    assert OutreachThread.objects.get(pk=thread.pk).traffic_light == "green"
    assert result.get("amber") == 0
    assert result.get("red") == 0


@pytest.mark.django_db
def test_run_no_reply_recent_send_untouched():
    from apps.crm.models import OutreachThread, Task
    from apps.outreach.triage import run_no_reply

    thread = _make_thread()
    # sent yesterday — well under threshold
    _make_active_sequence(
        thread, sent_message_id="<s4>", sent_at=timezone.now() - timedelta(days=1)
    )

    result = run_no_reply(now=timezone.now())

    assert OutreachThread.objects.get(pk=thread.pk).traffic_light == "green"
    assert not Task.objects.filter(thread=thread).exists()
    assert result == {"amber": 0, "red": 0}


# ---------------------------------------------------------------------------
# wiring — sync_google_gmail runs triage on fetched messages
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sync_google_gmail_calls_triage(settings):
    """``sync_google_gmail`` feeds the fetched messages into ``triage_inbound``."""
    from apps.joseph.models import GoogleIntegration
    from apps.joseph import tasks as joseph_tasks

    owner = _make_user("gm-owner@waiis.test")
    GoogleIntegration.objects.create(user=owner, refresh_token="r", scopes=["x"])

    fetched = [{"id": "m-1", "from": "pat@acme.org", "subject": "Re"}]

    with patch.object(joseph_tasks, "build_gmail_service"), patch.object(
        joseph_tasks, "recent_messages", return_value=fetched
    ), patch.object(joseph_tasks, "post_to_ingest"), patch(
        "apps.outreach.triage.triage_inbound", return_value={"matched": 1, "unmatched": 0, "paused": 1}
    ) as triage:
        joseph_tasks.sync_google_gmail()

    triage.assert_called_once_with(fetched)


# ---------------------------------------------------------------------------
# beat — outreach-no-reply registered (daily)
# ---------------------------------------------------------------------------


def test_outreach_no_reply_beat_registered():
    from jobs.schedules import BEAT_SCHEDULE

    assert "outreach-no-reply" in BEAT_SCHEDULE
    entry = BEAT_SCHEDULE["outreach-no-reply"]
    assert entry["task"] == "apps.outreach.tasks.run_no_reply_followups"
    assert int(entry["schedule"].run_every.total_seconds()) == 86400


@pytest.mark.django_db
def test_run_no_reply_followups_task_calls_run_no_reply():
    from apps.outreach.tasks import run_no_reply_followups

    with patch(
        "apps.outreach.tasks.run_no_reply", return_value={"amber": 1, "red": 0}
    ) as fn:
        result = run_no_reply_followups()

    fn.assert_called_once()
    assert result == {"amber": 1, "red": 0}
