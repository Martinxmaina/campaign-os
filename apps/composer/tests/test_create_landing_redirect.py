import pytest
from django.urls import reverse
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_create_landing_redirects_to_compose(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    resp = client.get(reverse("composer:create_landing", kwargs={"workspace_id": workspace.id}))
    assert resp.status_code == 302
    assert resp.url == reverse("composer:compose", kwargs={"workspace_id": workspace.id})
