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


@pytest.mark.django_db
def test_non_assignee_member_cannot_decide_others_post(client, organization, workspace):
    """A non-admin workspace member must not be able to decide on a post that is
    assigned to someone else, even by POSTing a crafted approval_id."""
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.approvals.models import ApprovalAction

    # The assignee who legitimately owns the review.
    assignee = User.objects.create_user(
        email="assignee@example.com", password="x", name="Assignee",
        tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.create(user=assignee, workspace=workspace, workspace_role="member")

    # An attacker: ordinary (non-admin) member of the same workspace.
    attacker = User.objects.create_user(
        email="attacker@example.com", password="x", name="Attacker",
        tos_accepted_at=timezone.now())
    OrgMembership.objects.create(user=attacker, organization=organization,
                                 org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=attacker, workspace=workspace, workspace_role="member")
    attacker.last_workspace_id = workspace.id
    attacker.save(update_fields=["last_workspace_id"])

    post = Post.objects.create(workspace=workspace, title="NotYours", caption="c",
        review_assignee=assignee, review_state="pending")

    client.force_login(attacker)
    url = reverse("console:approval-decide", args=[post.id])
    resp = client.post(url, {"decision": "approve"})

    assert resp.status_code == 403
    post.refresh_from_db()
    assert post.review_state == "pending"
    assert not ApprovalAction.objects.filter(post=post).exists()
