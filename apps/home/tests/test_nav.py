import pytest
from django.urls import reverse
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db
R = WorkspaceMembership.WorkspaceRole


def _home(client, workspace, user):
    client.force_login(user)
    return client.get(reverse("home:index", kwargs={"workspace_id": workspace.id})).content


def test_spine_present_for_everyone(client, workspace, make_user_in_workspace):
    html = _home(client, workspace, make_user_in_workspace(workspace, role=R.MANAGER))
    for label in [b"Home", b"Create", b"Calendar", b"Review", b"Inbox", b"Analytics", b"More"]:
        assert label in html


def test_content_only_hides_role_groups(client, workspace, make_user_in_workspace):
    html = _home(client, workspace, make_user_in_workspace(workspace, role=R.MANAGER))
    assert b"Joseph" not in html
    assert b"Relationships" not in html


def test_campaign_owner_sees_relationships_not_joseph(client, workspace, make_user_in_workspace):
    html = _home(client, workspace, make_user_in_workspace(workspace, role=R.CAMPAIGN_OWNER))
    assert b"Relationships" in html
    assert b"Joseph" not in html


def test_admin_sees_both_groups(client, workspace, make_user_in_workspace):
    html = _home(client, workspace, make_user_in_workspace(workspace, role=R.ADMIN))
    assert b"Joseph" in html and b"Relationships" in html
