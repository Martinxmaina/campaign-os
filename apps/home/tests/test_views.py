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
