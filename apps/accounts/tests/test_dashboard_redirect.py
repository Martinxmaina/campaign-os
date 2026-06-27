import pytest
from django.urls import reverse
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_root_redirects_to_home_not_calendar(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.url == reverse("home:index", kwargs={"workspace_id": workspace.id})
