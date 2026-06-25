# apps/approvals/tests/test_send_for_publish.py
import pytest
from django.urls import reverse
from apps.settings_manager.helpers import get_setting


@pytest.fixture
def reviewer(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.mark.django_db
def test_review_copy_email_default(workspace):
    # Falls back to the app default when no workspace/org override exists.
    assert get_setting(workspace.id, "review.copy_email") == "martin.maina@africacen.org"


from django.core import mail
from apps.composer.models import Post


@pytest.mark.django_db
def test_email_post_copy_sends_one_mail(workspace, reviewer):
    from apps.approvals.send_actions import email_post_copy
    post = Post.objects.create(workspace=workspace, title="Solar story",
        caption="Solar is booming across East Africa.", review_state="pending",
        review_assignee=reviewer)
    sent = email_post_copy(post, "ops@example.com", reviewer)
    assert sent is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ops@example.com"]
    assert "Solar is booming" in mail.outbox[0].body


@pytest.mark.django_db
def test_email_post_copy_no_address_is_noop(workspace, reviewer):
    from apps.approvals.send_actions import email_post_copy
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_state="pending", review_assignee=reviewer)
    assert email_post_copy(post, "", reviewer) is False
    assert len(mail.outbox) == 0


from apps.approvals.models import ApprovalAction


@pytest.mark.django_db
def test_send_for_publish_approves_emails_and_schedules(workspace, reviewer):
    from apps.approvals.send_actions import send_for_publish
    post = Post.objects.create(workspace=workspace, title="P",
        caption="Ship it across the corridor.", review_state="pending",
        review_assignee=reviewer)

    send_for_publish(post, reviewer)

    post.refresh_from_db()
    assert post.review_state == "approved"                      # approved
    assert post.scheduled_at is not None                        # scheduled to publish
    assert ApprovalAction.objects.filter(post=post, action="approved").exists()
    assert len(mail.outbox) == 1                                # one copy email
    assert mail.outbox[0].to == ["martin.maina@africacen.org"]  # to the default address


@pytest.mark.django_db
def test_send_for_publish_email_failure_is_nonfatal(workspace, reviewer, monkeypatch):
    """A broken mail backend must not stop approve + publish."""
    import apps.approvals.send_actions as sa
    from apps.approvals.send_actions import send_for_publish
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_state="pending", review_assignee=reviewer)

    def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(sa, "email_post_copy", boom)

    send_for_publish(post, reviewer)  # must not raise

    post.refresh_from_db()
    assert post.review_state == "approved"
    assert post.scheduled_at is not None


@pytest.mark.django_db
def test_non_assignee_cannot_send(client, organization, workspace):
    """A non-admin workspace member must not be able to POST decision=send
    on a post assigned to someone else (mirrors the existing approve guard)."""
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    assignee = User.objects.create_user(
        email="assignee2@example.com", password="x", name="Assignee",
        tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.create(user=assignee, workspace=workspace, workspace_role="member")

    attacker = User.objects.create_user(
        email="attacker2@example.com", password="x", name="Attacker",
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
    resp = client.post(url, {"decision": "send"})

    assert resp.status_code == 403
    post.refresh_from_db()
    assert post.review_state == "pending"   # state unchanged
    assert post.scheduled_at is None        # never scheduled


@pytest.mark.django_db
def test_gate_still_blocks_after_send(workspace, reviewer):
    """send_for_publish approves and schedules the post, but the gate remains
    authoritative: a platform post with no gate_id would still be blocked at
    publish time (the send path does not bypass the gate)."""
    from apps.approvals.send_actions import send_for_publish
    from apps.publisher.engine import PublishEngine

    post = Post.objects.create(workspace=workspace, title="P",
        caption="Gate must remain.", review_state="pending",
        review_assignee=reviewer)

    send_for_publish(post, reviewer)

    post.refresh_from_db()
    assert post.review_state == "approved"
    assert post.scheduled_at is not None

    # Confirm gate is still authoritative: no gate_id -> engine reports failure.
    for pp in post.platform_posts.all():
        assert not pp.gate_bypassed
        assert pp.gate_id is None
        assert PublishEngine()._gate_failure_reason(pp) == "missing gate_id"


@pytest.mark.django_db
def test_send_button_renders_in_queue(client, workspace, reviewer):
    Post.objects.create(workspace=workspace, title="Mine", caption="c",
        review_assignee=reviewer, review_state="pending")
    resp = client.get(reverse("console:approvals"))
    assert resp.status_code == 200
    assert b'value="send"' in resp.content
