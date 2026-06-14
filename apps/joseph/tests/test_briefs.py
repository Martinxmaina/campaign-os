"""Tests for the briefs index at /joseph/briefs/ — the bottom-nav "Brief"
destination (a thread-less /joseph/brief/ 404s). Lists agent-service threads,
each linking to its L0 brief card. Gated by ``_can_access_joseph`` and graceful
when the agent-service is down (empty list, never a 500).
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


THREADS = [
    {"id": "t-prop", "org": "Rockefeller", "stage": "proposal", "traffic_light": "red",
     "quintile": 4, "track": "catalytic capital"},
    {"id": "t-comm", "org": "Mission 300", "stage": "committed", "traffic_light": "green",
     "quintile": 5, "track": "energy access"},
]


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
def test_briefs_lists_threads_linking_to_brief(joseph, client):
    with patch("apps.joseph.views.readers.list_threads", return_value=THREADS):
        resp = client.get(reverse("joseph:briefs"))
    assert resp.status_code == 200
    assert b"Rockefeller" in resp.content
    # each row links to that thread's L0 brief card
    assert reverse("joseph:brief", args=["t-prop"]).encode() in resp.content


@pytest.mark.django_db
def test_briefs_forbidden_for_viewer(viewer, client):
    with patch("apps.joseph.views.readers.list_threads") as lt:
        resp = client.get(reverse("joseph:briefs"))
    assert resp.status_code in (403, 302)
    lt.assert_not_called()


@pytest.mark.django_db
def test_briefs_agent_down_renders_empty_no_500(joseph, client):
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        resp = client.get(reverse("joseph:briefs"))
    assert resp.status_code == 200
    assert b"No threads yet." in resp.content


@pytest.mark.django_db
def test_briefs_csp_safe(joseph, client):
    with patch("apps.joseph.views.readers.list_threads", return_value=THREADS):
        resp = client.get(reverse("joseph:briefs"))
    assert b"onclick=" not in resp.content and b"onsubmit=" not in resp.content
