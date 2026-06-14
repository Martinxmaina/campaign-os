"""Tests for the team thread CRUD surface (Task 8) at /crm/threads/<id>/.

The canonical thread now lives in Django (``apps.crm.OutreachThread``). The team
can, from the thread surface:

  POST /crm/threads/<id>/edit/      → update stage / owner / next_action
  POST /crm/threads/<id>/activity/  → append an Activity (the append-only log)
  POST /crm/threads/<id>/task/      → create a Task

Every view is gated by ``_can_manage_crm`` (staff or an owner/admin/campaign_owner
workspace role), CSP-safe (no inline handlers), and is pure Django — the dossier
is the only thing still fetched from agent-service (by id), and that read is
mocked here.
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


# ---------------------------------------------------------------------------
# Role fixtures (mirror test_crm_views.py) — manager passes, viewer 403s.
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(client, org_owner, workspace):
    """A workspace owner — passes ``_can_manage_crm``."""
    from apps.members.models import WorkspaceMembership

    WorkspaceMembership.objects.create(
        user=org_owner, workspace=workspace, workspace_role="owner"
    )
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def viewer(client, db, organization, workspace):
    """An ordinary member (viewer) — must be 403'd from the thread surface."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from django.utils import timezone

    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(
        user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER
    )
    WorkspaceMembership.objects.create(
        user=u, workspace=workspace, workspace_role="member"
    )
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


@pytest.fixture
def thread(db):
    """A CRM org + contact + outreach thread (with a dossier_id)."""
    from apps.crm.models import Contact, Organization, OutreachThread

    org = Organization.objects.create(
        name="Rockefeller Foundation",
        type=Organization.Type.FUNDER,
        tier=Organization.Tier.T1,
        track_tags=["ai10bn"],
    )
    okonkwo = Contact.objects.create(
        org=org, full_name="Dr. Okonkwo",
        seniority=Contact.Seniority.VP, email="okonkwo@rockefeller.org",
    )
    return OutreachThread.objects.create(
        org=org, primary_contact=okonkwo, stage=OutreachThread.Stage.ENGAGED,
        track="ai10bn", traffic_light="amber", quintile=4, score=0.7,
        dossier_id="d1",
    )


# ---------------------------------------------------------------------------
# edit — stage / owner / next_action
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_thread_edit_updates_stage_owner_next_action(manager, client, thread):
    resp = client.post(
        reverse("crm:thread-edit", args=[thread.id]),
        {
            "stage": "proposal_sent",
            "owner": str(manager.id),
            "next_action": "Send the catalytic-capital deck",
        },
    )
    assert resp.status_code in (200, 302)
    thread.refresh_from_db()
    assert thread.stage == "proposal_sent"
    assert thread.owner_id == manager.id
    assert thread.next_action == "Send the catalytic-capital deck"


@pytest.mark.django_db
def test_thread_edit_forbidden_for_viewer(viewer, client, thread):
    resp = client.post(
        reverse("crm:thread-edit", args=[thread.id]),
        {"stage": "closed", "next_action": "nope"},
    )
    assert resp.status_code == 403
    thread.refresh_from_db()
    assert thread.stage == "engaged"  # unchanged


# ---------------------------------------------------------------------------
# activity — append-only log
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_thread_activity_appends_activity(manager, client, thread):
    from apps.crm.models import Activity

    resp = client.post(
        reverse("crm:thread-activity", args=[thread.id]),
        {"activity_type": "note", "body": "Spoke with Dr. Okonkwo at the summit."},
    )
    assert resp.status_code in (200, 302)
    acts = Activity.objects.filter(thread=thread)
    assert acts.count() == 1
    a = acts.first()
    assert a.activity_type == "note"
    assert a.actor_id == manager.id
    assert a.actor_type == "human"
    assert "summit" in (a.content_ref.get("body") or "")


@pytest.mark.django_db
def test_thread_activity_forbidden_for_viewer(viewer, client, thread):
    from apps.crm.models import Activity

    resp = client.post(
        reverse("crm:thread-activity", args=[thread.id]),
        {"activity_type": "note", "body": "nope"},
    )
    assert resp.status_code == 403
    assert not Activity.objects.filter(thread=thread).exists()


# ---------------------------------------------------------------------------
# task — create a Task
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_thread_task_creates_task(manager, client, thread):
    from apps.crm.models import Task

    resp = client.post(
        reverse("crm:thread-task", args=[thread.id]),
        {"type": "send_email", "due": "2026-06-30"},
    )
    assert resp.status_code in (200, 302)
    tasks = Task.objects.filter(thread=thread)
    assert tasks.count() == 1
    t = tasks.first()
    assert t.type == "send_email"
    assert t.owner_id == manager.id
    assert t.status == "open"


@pytest.mark.django_db
def test_thread_task_forbidden_for_viewer(viewer, client, thread):
    from apps.crm.models import Task

    resp = client.post(
        reverse("crm:thread-task", args=[thread.id]),
        {"type": "send_email"},
    )
    assert resp.status_code == 403
    assert not Task.objects.filter(thread=thread).exists()
