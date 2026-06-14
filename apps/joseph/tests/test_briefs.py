"""Tests for the briefs index at /joseph/briefs/ — the bottom-nav "Brief"
destination (a thread-less /joseph/brief/ 404s). Lists local CRM threads (the
canonical source after the strangler step), each linking to its L0 brief card.
Gated by ``_can_access_joseph``; an empty DB renders an empty list, never a 500.
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


def _make_thread(*, org_name, stage, traffic_light="green", quintile=0, track=""):
    from apps.crm.models import Organization, OutreachThread
    org, _ = Organization.objects.get_or_create(name=org_name)
    return OutreachThread.objects.create(
        org=org, stage=stage, traffic_light=traffic_light, quintile=quintile, track=track,
    )


@pytest.fixture
def seed_threads(db):
    t1 = _make_thread(org_name="Rockefeller", stage="proposal_sent", traffic_light="red",
                      quintile=4, track="catalytic capital")
    t2 = _make_thread(org_name="Mission 300", stage="committed", traffic_light="green",
                      quintile=5, track="energy access")
    return {"prop": t1, "comm": t2}


@pytest.fixture
def joseph(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def viewer(client, db, organization, workspace):
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    u = User.objects.create_user(
        email="viewer-briefs@example.com", password="x", name="Viewer", tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


@pytest.mark.django_db
def test_briefs_lists_threads_linking_to_brief(joseph, client, seed_threads):
    resp = client.get(reverse("joseph:briefs"))
    assert resp.status_code == 200
    assert b"Rockefeller" in resp.content
    # each row links to that thread's L0 brief card (by Django pk)
    assert reverse("joseph:brief", args=[str(seed_threads["prop"].id)]).encode() in resp.content


@pytest.mark.django_db
def test_briefs_forbidden_for_viewer(viewer, client):
    resp = client.get(reverse("joseph:briefs"))
    assert resp.status_code in (403, 302)


@pytest.mark.django_db
def test_briefs_empty_renders_empty_no_500(joseph, client):
    resp = client.get(reverse("joseph:briefs"))
    assert resp.status_code == 200
    assert b"No threads yet." in resp.content


@pytest.mark.django_db
def test_briefs_csp_safe(joseph, client, seed_threads):
    resp = client.get(reverse("joseph:briefs"))
    assert b"onclick=" not in resp.content and b"onsubmit=" not in resp.content
