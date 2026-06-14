"""Tests for multi-step outreach sequences — models + enroll + advance.

A ``SequenceTemplate`` holds the reusable step plan (a list of email /
human-channel steps each with a ``delay_days``). ``enroll(thread, template)``
materialises a ``Sequence`` for the thread plus one ``SequenceStep`` per template
step, with ``scheduled_for`` = ``now + cumulative delay_days``. The daily
``advance()`` sweep:

  * sends a **due email step** via the gated ``send_email`` orchestrator (mocked
    here — no real send, no real gate) and marks the step ``sent``;
  * for a **due human-channel step** (linkedin / whatsapp / call) it creates a
    ``crm.Task`` for the thread owner and marks the step ``task_open`` — never an
    auto-send;
  * leaves a **future step** untouched;
  * sets the ``Sequence`` to ``completed`` once every step is resolved.

The Celery beat task ``advance_sequences`` (registered as ``outreach-advance``)
wraps ``advance()``. All network is mocked.
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


def _make_thread(track="energy", owner=None):
    from apps.crm.models import Contact, Organization, OutreachThread

    org = Organization.objects.create(name="Acme Capital")
    contact = Contact.objects.create(org=org, full_name="Pat Lee", email="pat@acme.org")
    if owner is None:
        owner = _make_user("thread-owner@waiis.test")
    return OutreachThread.objects.create(
        org=org, primary_contact=contact, track=track, owner=owner
    )


def _make_mailbox(owner, email="joseph@africacen.org"):
    from apps.outreach.models import Mailbox

    return Mailbox.objects.create(
        user=owner,
        email=email,
        daily_cap=50,
        ramp_started_at=timezone.now() - timedelta(days=21),
    )


def _make_template(steps=None):
    from apps.outreach.models import SequenceTemplate

    if steps is None:
        steps = [
            {"kind": "email", "delay_days": 0, "subject": "Intro", "body": "<p>Hi</p>"},
            {"kind": "email", "delay_days": 3, "subject": "Bump", "body": "<p>Following up</p>"},
        ]
    return SequenceTemplate.objects.create(name="nurture", steps=steps)


# ---------------------------------------------------------------------------
# models round-trip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_models_round_trip():
    from apps.outreach.models import Sequence, SequenceStep, SequenceTemplate

    tmpl = _make_template()
    assert SequenceTemplate.objects.get(pk=tmpl.pk).steps[0]["kind"] == "email"

    thread = _make_thread()
    seq = Sequence.objects.create(template=tmpl, thread=thread)
    assert seq.status == Sequence.Status.ACTIVE

    step = SequenceStep.objects.create(
        sequence=seq,
        position=1,
        kind="email",
        subject="Intro",
        body="<p>Hi</p>",
        delay_days=0,
        scheduled_for=timezone.now(),
    )
    fetched = SequenceStep.objects.get(pk=step.pk)
    assert fetched.sequence_id == seq.id
    assert fetched.status == SequenceStep.Status.PENDING


# ---------------------------------------------------------------------------
# enroll
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_enroll_creates_sequence_and_steps_with_cumulative_schedule():
    from apps.outreach.models import Sequence, SequenceStep
    from apps.outreach.sequences import enroll

    thread = _make_thread()
    tmpl = _make_template(
        [
            {"kind": "email", "delay_days": 0, "subject": "Intro", "body": "<p>Hi</p>"},
            {"kind": "linkedin", "delay_days": 2, "subject": "", "body": "Connect on LI"},
            {"kind": "email", "delay_days": 5, "subject": "Bump", "body": "<p>Bump</p>"},
        ]
    )

    before = timezone.now()
    seq = enroll(thread, tmpl)
    after = timezone.now()

    assert isinstance(seq, Sequence)
    assert seq.thread_id == thread.id
    assert seq.template_id == tmpl.id
    assert seq.status == Sequence.Status.ACTIVE

    steps = list(SequenceStep.objects.filter(sequence=seq).order_by("position"))
    assert [s.position for s in steps] == [1, 2, 3]
    assert [s.kind for s in steps] == ["email", "linkedin", "email"]
    assert all(s.status == SequenceStep.Status.PENDING for s in steps)

    # scheduled_for = now + cumulative delay_days (0, 0+2, 0+2+5 = 0, 2, 7)
    assert before <= steps[0].scheduled_for <= after + timedelta(seconds=2)
    assert steps[1].scheduled_for >= before + timedelta(days=2)
    assert steps[1].scheduled_for <= after + timedelta(days=2, seconds=2)
    assert steps[2].scheduled_for >= before + timedelta(days=7)
    assert steps[2].scheduled_for <= after + timedelta(days=7, seconds=2)


# ---------------------------------------------------------------------------
# advance — due email step → gated send + marked sent
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_advance_sends_due_email_step_via_send_email():
    from apps.outreach.models import Sequence, SequenceStep
    from apps.outreach.sequences import advance, enroll

    owner = _make_user("owner-em@waiis.test")
    thread = _make_thread(owner=owner)
    _make_mailbox(owner)
    tmpl = _make_template(
        [{"kind": "email", "delay_days": 0, "subject": "Intro", "body": "<p>Hi</p>"}]
    )
    seq = enroll(thread, tmpl)

    with patch("apps.outreach.sequences.send_email", return_value="m-1") as send:
        result = advance(now=timezone.now() + timedelta(minutes=1))

    send.assert_called_once()
    # the drafted subject/body rode through to send_email
    assert send.call_args.kwargs.get("subject") == "Intro"
    assert send.call_args.kwargs.get("body") == "<p>Hi</p>"

    step = SequenceStep.objects.get(sequence=seq, position=1)
    assert step.status == SequenceStep.Status.SENT
    # the only step is resolved → the sequence is completed
    assert Sequence.objects.get(pk=seq.pk).status == Sequence.Status.COMPLETED
    assert result.get("sent") == 1


# ---------------------------------------------------------------------------
# advance — due human-channel step → crm.Task + task_open (never auto-sent)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_advance_due_human_step_creates_task_and_does_not_send():
    from apps.crm.models import Task
    from apps.outreach.models import SequenceStep
    from apps.outreach.sequences import advance, enroll

    owner = _make_user("owner-hu@waiis.test")
    thread = _make_thread(owner=owner)
    tmpl = _make_template(
        [{"kind": "linkedin", "delay_days": 0, "subject": "", "body": "Connect on LI"}]
    )
    seq = enroll(thread, tmpl)

    with patch("apps.outreach.sequences.send_email") as send:
        result = advance(now=timezone.now() + timedelta(minutes=1))

    # a human-channel step is NEVER auto-sent
    send.assert_not_called()

    step = SequenceStep.objects.get(sequence=seq, position=1)
    assert step.status == SequenceStep.Status.TASK_OPEN

    task = Task.objects.get(thread=thread)
    assert task.owner_id == owner.id
    assert task.status == Task.Status.OPEN
    assert "linkedin" in task.type
    assert result.get("tasks") == 1


# ---------------------------------------------------------------------------
# advance — a future step is untouched
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_advance_leaves_future_step_untouched():
    from apps.outreach.models import Sequence, SequenceStep
    from apps.outreach.sequences import advance, enroll

    owner = _make_user("owner-fu@waiis.test")
    thread = _make_thread(owner=owner)
    _make_mailbox(owner)
    tmpl = _make_template(
        [{"kind": "email", "delay_days": 10, "subject": "Later", "body": "<p>Later</p>"}]
    )
    seq = enroll(thread, tmpl)

    with patch("apps.outreach.sequences.send_email") as send:
        result = advance(now=timezone.now())

    send.assert_not_called()
    step = SequenceStep.objects.get(sequence=seq, position=1)
    assert step.status == SequenceStep.Status.PENDING
    # nothing resolved → the sequence stays active
    assert Sequence.objects.get(pk=seq.pk).status == Sequence.Status.ACTIVE
    assert result.get("sent") == 0
    assert result.get("tasks") == 0


# ---------------------------------------------------------------------------
# advance — multi-step: only due steps fire, sequence completes when all done
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_advance_partial_then_complete():
    from apps.outreach.models import Sequence, SequenceStep
    from apps.outreach.sequences import advance, enroll

    owner = _make_user("owner-mx@waiis.test")
    thread = _make_thread(owner=owner)
    _make_mailbox(owner)
    tmpl = _make_template(
        [
            {"kind": "email", "delay_days": 0, "subject": "A", "body": "<p>A</p>"},
            {"kind": "email", "delay_days": 4, "subject": "B", "body": "<p>B</p>"},
        ]
    )
    seq = enroll(thread, tmpl)

    # First sweep: only the day-0 step is due.
    with patch("apps.outreach.sequences.send_email", return_value="m-a") as send:
        advance(now=timezone.now() + timedelta(minutes=1))
    assert send.call_count == 1
    assert SequenceStep.objects.get(sequence=seq, position=1).status == SequenceStep.Status.SENT
    assert SequenceStep.objects.get(sequence=seq, position=2).status == SequenceStep.Status.PENDING
    assert Sequence.objects.get(pk=seq.pk).status == Sequence.Status.ACTIVE

    # Second sweep, days later: the day-4 step is now due → sequence completes.
    with patch("apps.outreach.sequences.send_email", return_value="m-b") as send:
        advance(now=timezone.now() + timedelta(days=5))
    assert send.call_count == 1
    assert SequenceStep.objects.get(sequence=seq, position=2).status == SequenceStep.Status.SENT
    assert Sequence.objects.get(pk=seq.pk).status == Sequence.Status.COMPLETED


# ---------------------------------------------------------------------------
# beat task wraps advance + is registered
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_advance_sequences_task_calls_advance():
    from apps.outreach.tasks import advance_sequences

    with patch(
        "apps.outreach.tasks.advance", return_value={"sent": 2, "tasks": 1}
    ) as adv:
        result = advance_sequences()

    adv.assert_called_once()
    assert result == {"sent": 2, "tasks": 1}


def test_outreach_advance_beat_registered():
    from jobs.schedules import BEAT_SCHEDULE

    assert "outreach-advance" in BEAT_SCHEDULE
    entry = BEAT_SCHEDULE["outreach-advance"]
    assert entry["task"] == "apps.outreach.tasks.advance_sequences"
    # daily cadence
    assert int(entry["schedule"].run_every.total_seconds()) == 86400
