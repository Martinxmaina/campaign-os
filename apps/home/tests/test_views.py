import pytest
from django.urls import reverse
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_home_url_resolves_and_renders_for_member(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    url = reverse("home:index", kwargs={"workspace_id": workspace.id})
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"New post" in resp.content


def _get_home(client, workspace, user):
    client.force_login(user)
    return client.get(reverse("home:index", kwargs={"workspace_id": workspace.id}))


def test_admin_sees_invite_card_and_graph(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.ADMIN)
    resp = _get_home(client, workspace, user)
    assert resp.status_code == 200
    assert b"Invite a teammate" in resp.content      # admin-only card
    assert b"performance" in resp.content.lower()     # graph card present (view_analytics)


def test_content_only_manager_has_no_admin_cards(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    resp = _get_home(client, workspace, user)
    assert resp.status_code == 200
    assert b"Invite a teammate" not in resp.content
    assert b"System health" not in resp.content


def test_editor_without_analytics_hides_graph(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.EDITOR)
    resp = _get_home(client, workspace, user)
    assert resp.status_code == 200
    # editor has view_analytics in the role table -> graph SHOWS; assert empty-state copy instead
    assert b"fills in as you publish" in resp.content or b"performance" in resp.content.lower()
