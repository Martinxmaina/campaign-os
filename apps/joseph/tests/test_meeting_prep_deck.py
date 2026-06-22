"""Tests for the proactive T-5 deck auto-assemble hook (TB.5 Task 4).

The pre-meeting cascade's T-5 stage (TB.3) gains a deck trigger: when a meeting
is ≤5 days out for a linked thread that has **no current deck** (or whose newest
deck is **>30 days old**), the cascade enqueues ``assemble_deck`` with the default
skeleton for the thread's audience_type+track and notifies Joseph.

It is idempotent — the trigger is recorded as a ``deck`` stage in the event's
``prep_stages`` ledger, so a later sweep of the same event never re-assembles.
A thread with a fresh (≤30d) deck is left alone.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.joseph import meeting_prep
from apps.joseph.models import CalendarEvent


@pytest.fixture
def joseph(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership

    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    return org_owner


def _thread(owner=None, *, org_name="Rockefeller Foundation", org_type=None, track="ai10bn"):
    from apps.crm.models import Organization, OutreachThread

    kw = {}
    if org_type is not None:
        kw["type"] = org_type
    org = Organization.objects.create(name=org_name, **kw)
    return OutreachThread.objects.create(org=org, track=track, owner=owner)


def _linked_event(workspace, thread, *, days_out, gid="g1"):
    return CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id=gid,
        title=f"{thread.org.name} sync",
        start=timezone.now() + timedelta(days=days_out),
        linked_thread_id=str(thread.id),
        briefing_status="linked",
    )


# --------------------------------------------------------------------------
# T-5 enqueues assemble when the thread has no current deck
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_t5_enqueues_deck_when_thread_has_no_deck(joseph, workspace):
    thread = _thread(owner=joseph)
    ev = _linked_event(workspace, thread, days_out=5)
    with patch("apps.joseph.meeting_prep.readers.compile_dossier"), patch(
        "apps.decks.tasks.assemble_deck_task.delay"
    ) as enqueue:
        meeting_prep.check_meeting_prep()
    enqueue.assert_called_once()
    # enqueued for THIS thread, with a real skeleton id resolved from audience+track
    kwargs = enqueue.call_args.kwargs
    args = enqueue.call_args.args
    assembled_thread_id = kwargs.get("thread_id") or (args[0] if args else None)
    skeleton_id = kwargs.get("skeleton_id") or (args[1] if len(args) > 1 else None)
    assert assembled_thread_id == str(thread.id)
    from apps.decks import skeletons

    assert skeletons.get(skeleton_id) is not None
    ev.refresh_from_db()
    assert "deck" in ev.prep_stages


@pytest.mark.django_db
def test_t5_deck_trigger_is_idempotent(joseph, workspace):
    thread = _thread(owner=joseph)
    _linked_event(workspace, thread, days_out=5)
    with patch("apps.joseph.meeting_prep.readers.compile_dossier"), patch(
        "apps.decks.tasks.assemble_deck_task.delay"
    ) as enqueue:
        meeting_prep.check_meeting_prep()
        meeting_prep.check_meeting_prep()
    # second sweep must NOT re-assemble (the 'deck' stage is already recorded)
    assert enqueue.call_count == 1


@pytest.mark.django_db
def test_t5_does_not_enqueue_when_deck_is_fresh(joseph, workspace):
    """A thread with a deck ≤30 days old is left alone — no re-assemble."""
    from apps.decks.models import DeckRegistry

    thread = _thread(owner=joseph)
    DeckRegistry.objects.create(
        thread=thread, skeleton_id="philanthropy_anchor", status=DeckRegistry.Status.SENT
    )
    _linked_event(workspace, thread, days_out=5)
    with patch("apps.joseph.meeting_prep.readers.compile_dossier"), patch(
        "apps.decks.tasks.assemble_deck_task.delay"
    ) as enqueue:
        meeting_prep.check_meeting_prep()
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_t5_enqueues_when_newest_deck_is_stale(joseph, workspace):
    """A deck older than 30 days re-triggers an auto-assemble."""
    from apps.decks.models import DeckRegistry

    thread = _thread(owner=joseph)
    old = DeckRegistry.objects.create(
        thread=thread, skeleton_id="philanthropy_anchor", status=DeckRegistry.Status.SENT
    )
    DeckRegistry.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
    _linked_event(workspace, thread, days_out=5)
    with patch("apps.joseph.meeting_prep.readers.compile_dossier"), patch(
        "apps.decks.tasks.assemble_deck_task.delay"
    ) as enqueue:
        meeting_prep.check_meeting_prep()
    enqueue.assert_called_once()


@pytest.mark.django_db
def test_t5_deck_trigger_notifies_joseph(joseph, workspace):
    from apps.notifications.models import EventType, Notification

    thread = _thread(owner=joseph)
    _linked_event(workspace, thread, days_out=5)
    with patch("apps.joseph.meeting_prep.readers.compile_dossier"), patch(
        "apps.decks.tasks.assemble_deck_task.delay"
    ):
        meeting_prep.check_meeting_prep()
    # owner is notified that a deck is being prepared (deck_ready event channel)
    assert Notification.objects.filter(
        event_type=EventType.DECK_READY, user=joseph
    ).exists()


@pytest.mark.django_db
def test_skeleton_for_thread_resolves_audience_and_track(db, joseph):
    """The default-skeleton resolver maps the org type → audience skeleton."""
    from apps.crm.models import Organization
    from apps.decks.continuity import skeleton_for_thread

    funder = _thread(org_type=Organization.Type.FUNDER, org_name="A")
    assert skeleton_for_thread(funder) == "philanthropy_anchor"
    bilateral = _thread(org_type=Organization.Type.BILATERAL, org_name="B")
    assert skeleton_for_thread(bilateral) == "bilateral_ta"
    dfi = _thread(org_type=Organization.Type.DFI, org_name="C")
    assert skeleton_for_thread(dfi) == "dfi"
    corporate = _thread(org_type=Organization.Type.CORPORATE, org_name="D")
    assert skeleton_for_thread(corporate) == "corporate_sponsor"


@pytest.mark.django_db
def test_t5_deck_trigger_does_not_break_other_stages(joseph, workspace):
    """Adding the deck trigger leaves the existing T-5 dossier refresh intact."""
    thread = _thread(owner=joseph)
    ev = _linked_event(workspace, thread, days_out=5)
    with patch("apps.joseph.meeting_prep.readers.compile_dossier") as compile_mock, patch(
        "apps.decks.tasks.assemble_deck_task.delay"
    ):
        meeting_prep.check_meeting_prep()
    compile_mock.assert_called_once()
    ev.refresh_from_db()
    assert "t5" in ev.prep_stages
    assert "deck" in ev.prep_stages
