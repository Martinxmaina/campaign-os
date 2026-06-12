# apps/approvals/tests/test_ai_approvals_queue.py
import pytest
from django.urls import reverse
from apps.composer.models import Post


@pytest.fixture
def reviewer(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.mark.django_db
def test_queue_shows_my_pending_posts(client, reviewer, workspace):
    mine = Post.objects.create(workspace=workspace, title="Mine", caption="c",
        review_assignee=reviewer, review_state="pending")
    Post.objects.create(workspace=workspace, title="Draftish", caption="c", review_state="none")
    resp = client.get(reverse("console:approvals"))
    assert resp.status_code == 200
    assert b"Mine" in resp.content
    assert b"Draftish" not in resp.content


@pytest.mark.django_db
def test_approve_sets_state_and_records_action(client, reviewer, workspace):
    from apps.approvals.models import ApprovalAction
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_assignee=reviewer, review_state="pending")
    url = reverse("console:approval-decide", args=[post.id])
    resp = client.post(url, {"decision": "approve"})
    assert resp.status_code in (200, 302)
    post.refresh_from_db()
    assert post.review_state == "approved"
    assert ApprovalAction.objects.filter(post=post, action="approved").exists()


@pytest.mark.django_db
def test_reject_and_changes(client, reviewer, workspace):
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_assignee=reviewer, review_state="pending")
    url = reverse("console:approval-decide", args=[post.id])
    client.post(url, {"decision": "reject"})
    post.refresh_from_db()
    assert post.review_state == "rejected"
