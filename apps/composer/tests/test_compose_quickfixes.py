"""Render-smoke tests for the compose-page quick fixes.

These guard that templates/composer/compose.html still renders 200 for both
the new-post and edit-post views after the three UX fixes:

  (A) schedule date/time popover (#5)
  (B) caption -> preview / char-count immediacy (#6)
  (C) per-channel char-limit guardrail (#7)

They are intentionally cheap: a 200 + a few load-bearing markers (the caption
field, the schedule date/time fields, and the per-channel guardrail wiring).
"""

import pytest
from django.urls import reverse

from apps.members.models import WorkspaceMembership


@pytest.fixture
def manager_client(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(
        workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER
    )
    client.force_login(user)
    return client, user, workspace


def test_compose_new_renders_200(manager_client):
    client, _user, workspace = manager_client
    url = reverse("composer:compose", kwargs={"workspace_id": workspace.id})

    resp = client.get(url)

    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    # (B) caption field still present and named for the server + htmx preview.
    assert 'name="caption"' in body
    # (A) schedule date/time fields still present and named for the form.
    assert 'name="scheduled_date"' in body
    assert 'name="scheduled_time"' in body
    # (A) schedule inputs no longer carry form-datetime (so base.html's global
    # body-anchored flatpickr auto-init skips them); they use the inline class.
    assert "compose-sched-datetime" in body
    # (C) per-channel guardrail wiring is in the template.
    assert "anyOverLimit" in body
    assert "channelUsage" in body


def test_compose_edit_renders_200(manager_client, make_post):
    client, user, workspace = manager_client
    post = make_post(workspace, author=user)
    url = reverse(
        "composer:compose_edit",
        kwargs={"workspace_id": workspace.id, "post_id": post.id},
    )

    resp = client.get(url)

    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    assert 'name="caption"' in body
    assert 'name="scheduled_date"' in body
    assert 'name="scheduled_time"' in body
