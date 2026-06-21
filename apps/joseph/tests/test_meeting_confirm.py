"""Tests for the one-tap meeting confirm + routing surface (TB.4, Task 6).

The confirm screen at ``/joseph/meeting/<extracted_meeting_id>/`` is the last
step of the capture loop: it lists the ``ExtractedItem`` lines of a pending
``ExtractedMeeting`` with accept/edit/dismiss (+ a bulk-accept) and, on confirm,
routes every accepted item by its ``kind`` into the canonical Django surfaces —

- ``commitment_*`` → Activity(commitment_recorded) **+** a stage-proposal Task
  (``confirm_commitment``, owner=Joseph) surfaced to his queue;
- ``interest_expressed | objection_raised | strategy_signal`` → Activity(note)
  only (no stage change);
- ``next_step`` → Task (owner defaults to Joseph, due=proposed_due);
- ``intelligence_signal`` (+ wiki_update_candidate) → a WikiRevisionCandidate
  (status=proposed, **never auto-applied**);
- ``content_idea`` → ContentIntake(status=IDEA, submitted_by=Joseph, pillar
  pre-filled, sensitivity inferred from the track);
- a ``warmth_delta`` on the meeting → updates ``thread.warmth`` + triggers a
  rescore; a dismissed item logs Activity(note, "outcome logged") and nothing
  else. Confirming marks the meeting ``confirmed``.

Gated by ``_can_access_joseph``; CSP-safe (POST forms, no inline handlers).
"""
from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.content_intake.models import ContentIntake
from apps.crm.models import Activity, Organization, OutreachThread, Task
from apps.joseph.models import (
    ExtractedItem,
    ExtractedMeeting,
    WikiRevisionCandidate,
)


# --------------------------------------------------------------------------
# fixtures (reuse the established joseph/owner pattern)
# --------------------------------------------------------------------------


@pytest.fixture
def joseph(client, org_owner, workspace):
    """Joseph = an owner of the workspace (can access the principal surface)."""
    from apps.members.models import WorkspaceMembership

    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def viewer(client, db, organization, workspace):
    """An ordinary workspace member (viewer) — must not reach the confirm surface."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


def _thread(*, owner=None, org_name="Rockefeller Foundation", track="energy", pillar="energy", warmth="warm"):
    org = Organization.objects.create(name=org_name)
    return OutreachThread.objects.create(
        org=org, track=track, pillar=pillar, owner=owner, warmth=warmth
    )


def _meeting(thread, *, warmth_delta=""):
    return ExtractedMeeting.objects.create(
        thread=thread,
        source=ExtractedMeeting.Source.VOICE,
        transcript="t",
        warmth_delta=warmth_delta,
        status=ExtractedMeeting.Status.PENDING,
    )


def _item(meeting, kind, **kw):
    return ExtractedItem.objects.create(meeting=meeting, kind=kind, **kw)


# --------------------------------------------------------------------------
# GET /joseph/meeting/<id>/ — list with accept/edit/dismiss + bulk-accept
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_confirm_get_lists_items(client, joseph, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    _item(meeting, ExtractedItem.Kind.NEXT_STEP, description="Send the concept note")
    resp = client.get(reverse("joseph:meeting", args=[str(meeting.id)]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Send the concept note" in body
    # the confirm/route POST endpoint is present
    assert reverse("joseph:meeting-confirm", args=[str(meeting.id)]) in body


@pytest.mark.django_db
def test_confirm_get_is_csp_safe(client, joseph, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    _item(meeting, ExtractedItem.Kind.NEXT_STEP, description="x")
    resp = client.get(reverse("joseph:meeting", args=[str(meeting.id)]))
    body = resp.content.decode()
    assert "onclick=" not in body
    assert "onsubmit=" not in body
    import re

    for tag in re.findall(r"<script\b[^>]*>", body):
        if "src=" in tag:
            continue
        assert "nonce=" in tag


@pytest.mark.django_db
def test_confirm_get_role_gated(client, viewer, workspace):
    thread = _thread()
    meeting = _meeting(thread)
    resp = client.get(reverse("joseph:meeting", args=[str(meeting.id)]))
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# routing — commitment_* → Activity(commitment_recorded) + confirm Task
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_commitment_routes_to_activity_and_confirm_task(client, joseph, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    item = _item(
        meeting,
        ExtractedItem.Kind.COMMITMENT_FINANCIAL,
        description="They will fund 2M over 3 years",
    )
    resp = client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {f"action_{item.id}": "accept"},
    )
    assert resp.status_code in (200, 302)
    assert Activity.objects.filter(
        thread=thread, activity_type="commitment_recorded"
    ).exists()
    # a stage-proposal Task surfaced to Joseph's queue
    task = Task.objects.get(thread=thread, type="confirm_commitment")
    assert task.owner_id == joseph.id
    assert task.status == Task.Status.OPEN
    item.refresh_from_db()
    assert item.state == ExtractedItem.State.ACCEPTED


# --------------------------------------------------------------------------
# routing — interest/objection/strategy → Activity(note) only
# --------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind",
    [
        ExtractedItem.Kind.INTEREST_EXPRESSED,
        ExtractedItem.Kind.OBJECTION_RAISED,
        ExtractedItem.Kind.STRATEGY_SIGNAL,
    ],
)
def test_signal_routes_to_note_only(client, joseph, workspace, kind):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    item = _item(meeting, kind, description="signal")
    client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {f"action_{item.id}": "accept"},
    )
    assert Activity.objects.filter(thread=thread, activity_type="note").exists()
    # no stage-change Task, no commitment activity
    assert not Task.objects.filter(thread=thread).exists()
    assert not Activity.objects.filter(
        thread=thread, activity_type="commitment_recorded"
    ).exists()


# --------------------------------------------------------------------------
# routing — next_step → Task (owner=Joseph, due=proposed_due)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_next_step_routes_to_task(client, joseph, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    item = _item(
        meeting,
        ExtractedItem.Kind.NEXT_STEP,
        description="Send concept note",
        proposed_due=date(2026, 7, 1),
    )
    client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {f"action_{item.id}": "accept"},
    )
    task = Task.objects.get(thread=thread, type="next_step")
    assert task.owner_id == joseph.id
    assert str(task.due) == "2026-07-01"
    assert task.status == Task.Status.OPEN


# --------------------------------------------------------------------------
# routing — intelligence_signal + wiki flag → WikiRevisionCandidate (proposed)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_intelligence_signal_routes_to_wiki_candidate_proposed(client, joseph, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    item = _item(
        meeting,
        ExtractedItem.Kind.INTELLIGENCE_SIGNAL,
        description="New climate-finance facility coming",
        wiki_update_candidate=True,
    )
    client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {f"action_{item.id}": "accept"},
    )
    cand = WikiRevisionCandidate.objects.get(source_meeting=meeting)
    # never auto-applied
    assert cand.status == WikiRevisionCandidate.Status.PROPOSED
    assert cand.org_id == thread.org_id
    assert cand.thread_id == thread.id


@pytest.mark.django_db
def test_intelligence_signal_without_wiki_flag_is_note_only(client, joseph, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    item = _item(
        meeting,
        ExtractedItem.Kind.INTELLIGENCE_SIGNAL,
        description="minor aside",
        wiki_update_candidate=False,
    )
    client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {f"action_{item.id}": "accept"},
    )
    assert not WikiRevisionCandidate.objects.exists()
    assert Activity.objects.filter(thread=thread, activity_type="note").exists()


# --------------------------------------------------------------------------
# routing — content_idea → ContentIntake(IDEA, submitted_by=Joseph)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_content_idea_routes_to_content_intake(client, joseph, workspace):
    thread = _thread(owner=joseph, track="energy", pillar="Energy access")
    meeting = _meeting(thread)
    item = _item(
        meeting,
        ExtractedItem.Kind.CONTENT_IDEA,
        description="Write up the off-grid milestone",
    )
    client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {f"action_{item.id}": "accept"},
    )
    intake = ContentIntake.objects.get(workspace=workspace)
    assert intake.status == ContentIntake.Status.IDEA
    assert intake.submitted_by_id == joseph.id
    assert intake.pillar_theme == "Energy access"
    # sensitivity is inferred from the track, never blank
    assert intake.sensitivity in ContentIntake.Sensitivity.values


# --------------------------------------------------------------------------
# warmth — confirming with a warmth_delta updates thread.warmth + rescores
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_confirm_with_warmth_delta_updates_warmth_and_rescores(client, joseph, workspace):
    thread = _thread(owner=joseph, warmth="cold")
    meeting = _meeting(thread, warmth_delta="warmer")
    item = _item(meeting, ExtractedItem.Kind.NEXT_STEP, description="x")
    from unittest.mock import patch

    with patch("apps.joseph.routing.score_all_threads") as rescore:
        client.post(
            reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
            {f"action_{item.id}": "accept"},
        )
        rescore.assert_called_once()
    thread.refresh_from_db()
    # "warmer" pushes cold → warm
    assert thread.warmth == "warm"


@pytest.mark.django_db
def test_confirm_cooler_delta_cools_warmth(client, joseph, workspace):
    thread = _thread(owner=joseph, warmth="hot")
    meeting = _meeting(thread, warmth_delta="cooler")
    item = _item(meeting, ExtractedItem.Kind.NEXT_STEP, description="x")
    with __import__("unittest.mock", fromlist=["patch"]).patch("apps.joseph.routing.score_all_threads"):
        client.post(
            reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
            {f"action_{item.id}": "accept"},
        )
    thread.refresh_from_db()
    assert thread.warmth == "warm"


# --------------------------------------------------------------------------
# dismiss — logs Activity(note, "outcome logged") and nothing else
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_dismissed_item_logs_note_only(client, joseph, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    item = _item(
        meeting,
        ExtractedItem.Kind.COMMITMENT_FINANCIAL,
        description="They will fund 2M",
    )
    client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {f"action_{item.id}": "dismiss"},
    )
    # a dismissed item creates none of the routed objects
    assert not Task.objects.filter(thread=thread).exists()
    assert not ContentIntake.objects.exists()
    assert not WikiRevisionCandidate.objects.exists()
    # it logs an "outcome logged" note
    note = Activity.objects.get(thread=thread, activity_type="note")
    assert "outcome logged" in (note.content_ref.get("summary") or "").lower()
    item.refresh_from_db()
    assert item.state == ExtractedItem.State.DISMISSED


# --------------------------------------------------------------------------
# bulk accept + confirm marks the meeting confirmed
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_accept_routes_all_and_confirms_meeting(client, joseph, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    nxt = _item(meeting, ExtractedItem.Kind.NEXT_STEP, description="Follow up")
    com = _item(meeting, ExtractedItem.Kind.COMMITMENT_INTRO, description="Intro to the chair")
    client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {"bulk": "accept"},
    )
    assert Task.objects.filter(thread=thread, type="next_step").exists()
    assert Task.objects.filter(thread=thread, type="confirm_commitment").exists()
    assert Activity.objects.filter(thread=thread, activity_type="commitment_recorded").exists()
    nxt.refresh_from_db()
    com.refresh_from_db()
    assert nxt.state == ExtractedItem.State.ACCEPTED
    assert com.state == ExtractedItem.State.ACCEPTED
    meeting.refresh_from_db()
    assert meeting.status == ExtractedMeeting.Status.CONFIRMED


@pytest.mark.django_db
def test_confirm_marks_meeting_confirmed(client, joseph, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    item = _item(meeting, ExtractedItem.Kind.NEXT_STEP, description="x")
    client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {f"action_{item.id}": "accept"},
    )
    meeting.refresh_from_db()
    assert meeting.status == ExtractedMeeting.Status.CONFIRMED


@pytest.mark.django_db
def test_confirm_role_gated(client, viewer, workspace):
    thread = _thread()
    meeting = _meeting(thread)
    item = _item(meeting, ExtractedItem.Kind.NEXT_STEP, description="x")
    resp = client.post(
        reverse("joseph:meeting-confirm", args=[str(meeting.id)]),
        {f"action_{item.id}": "accept"},
    )
    assert resp.status_code == 403
    assert not Task.objects.filter(thread=thread).exists()
    meeting.refresh_from_db()
    assert meeting.status == ExtractedMeeting.Status.PENDING
