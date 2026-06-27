"""Render-smoke for the Compose page (guards the Phase B density refactor).

Both the new-post and edit-post pages must render 200. The edit page must
contain "Schedule" — this is the guard that the {% if post %} 500-fix and the
schedule controls survive the layout refactor.
"""
import pytest
from django.urls import reverse

from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_compose_new_and_edit_render_200(client, workspace, make_user_in_workspace, make_post):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)

    new = client.get(reverse("composer:compose", kwargs={"workspace_id": workspace.id}))
    assert new.status_code == 200

    post = make_post(workspace, status="draft", author=user)
    edit = client.get(
        reverse("composer:compose_edit", kwargs={"workspace_id": workspace.id, "post_id": post.id})
    )
    assert edit.status_code == 200
    assert b"Schedule" in edit.content
