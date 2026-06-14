"""Tests for Joseph's home — the editorial/operational principal surface at /joseph/.

One view, two content-differentiated surfaces: mobile editorial (Today strip,
Action queue, Red threads, Your content) vs desktop operational shell. The view
is gated by ``_can_access_joseph`` and degrades gracefully when the agent-service
is down (empty states, never a 500).
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


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
    """An ordinary workspace member (viewer) — must not reach Joseph's surface."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer", tos_accepted_at=timezone.now())
    # Strip the singleton-owner memberships the signup signal auto-granted.
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


def _patch_all_empty():
    """Patch every agent-service-backed reader the home view touches to empty."""
    return [
        patch("apps.joseph.views.readers.list_threads", return_value=[]),
        patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]),
    ]


@pytest.mark.django_db
def test_home_renders_for_joseph(joseph, client):
    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = client.get(reverse("joseph:home"))
    assert resp.status_code == 200
    assert b"Action queue" in resp.content
    assert b"Red threads" in resp.content


@pytest.mark.django_db
def test_home_forbidden_for_viewer(viewer, client):
    """A non-owner/admin/principal member must not reach the surface, and the
    agent-service must not be hit at all."""
    with patch("apps.joseph.views.readers.list_threads") as lt:
        resp = client.get(reverse("joseph:home"))
    assert resp.status_code in (403, 302)
    lt.assert_not_called()


@pytest.mark.django_db
def test_home_agent_down_renders_empty_state_no_500(joseph, client):
    """Agent-service down → the real readers swallow AgentClientError and return
    safe defaults → the home view renders a 200 empty state, never a 500.

    We patch the underlying ``agent_get`` (the graceful layer is the readers), so
    this exercises the genuine degrade path end-to-end."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        resp = client.get(reverse("joseph:home") + "?view=mobile")
    assert resp.status_code == 200
    # empty states present, not a server error
    assert b"Action queue" in resp.content
    assert b"Red threads" in resp.content


@pytest.mark.django_db
def test_home_view_mobile_renders_bottom_nav(joseph, client):
    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = client.get(reverse("joseph:home") + "?view=mobile")
    assert resp.status_code == 200
    assert b"joseph/home_mobile.html" in b"".join(t.name.encode() for t in resp.templates if t.name)
    # the mobile bottom nav is present
    content = resp.content.lower()
    assert b"pipeline" in content
    assert b"compose" in content


@pytest.mark.django_db
def test_home_view_desktop_renders_desktop_template(joseph, client):
    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = client.get(reverse("joseph:home") + "?view=desktop")
    assert resp.status_code == 200
    names = [t.name for t in resp.templates if t.name]
    assert "joseph/home_desktop.html" in names


@pytest.mark.django_db
def test_home_surfaces_red_threads_and_actions(joseph, client):
    """Red threads come from the local CRM (traffic_light='red'); the action
    queue comes from JosephIntelligence.proposals()."""
    from apps.crm.models import Organization, OutreachThread
    org = Organization.objects.create(name="Mission 300")
    OutreachThread.objects.create(
        org=org, stage=OutreachThread.Stage.COMMITTED, traffic_light="red",
        next_action="18d no touch",
    )
    notif = {"id": "n1", "kind": "gate_flag", "body": "Gate block on AfDB post",
             "urgent": True, "action": {"href": "/x"}}
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[notif]):
        resp = client.get(reverse("joseph:home") + "?view=mobile")
    assert resp.status_code == 200
    assert b"Mission 300" in resp.content
    assert b"Gate Flag" in resp.content or b"Gate block on AfDB post" in resp.content
