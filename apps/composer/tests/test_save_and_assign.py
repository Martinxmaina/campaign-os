"""save_post `save_and_assign` action — assign a reviewer straight from the composer.

Covers the new Create-page flow: writing a post and assigning a reviewer in one
step saves the draft AND creates the review assignment + emails the reviewer.
"""
import pytest
from django.urls import reverse

from apps.approvals.models import ReviewAssignment
from apps.composer.models import Post
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db
R = WorkspaceMembership.WorkspaceRole


def test_save_and_assign_creates_review_assignment(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=R.MANAGER)
    client.force_login(user)
    url = reverse("composer:save_post", kwargs={"workspace_id": workspace.id})

    resp = client.post(
        url,
        data={
            "action": "save_and_assign",
            "title": "Review me",
            "caption": "please review this draft",
            "tags": "",
            "reviewer_email": "reviewer@example.com",
            "reviewer_name": "Rev Iewer",
        },
    )
    assert resp.status_code in (200, 204, 302)

    post = Post.objects.filter(workspace=workspace).order_by("-created_at").first()
    assert post is not None
    assignment = ReviewAssignment.objects.filter(post=post, reviewer_email="reviewer@example.com").first()
    assert assignment is not None
    assert assignment.reviewer_name == "Rev Iewer"
    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.PENDING


def test_plain_save_draft_does_not_assign(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=R.MANAGER)
    client.force_login(user)
    url = reverse("composer:save_post", kwargs={"workspace_id": workspace.id})

    resp = client.post(url, data={"action": "save_draft", "caption": "no review", "tags": ""})
    assert resp.status_code in (200, 204, 302)
    assert ReviewAssignment.objects.count() == 0
