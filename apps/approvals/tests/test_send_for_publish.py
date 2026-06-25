# apps/approvals/tests/test_send_for_publish.py
import pytest
from django.core import mail
from django.urls import reverse

from apps.approvals.models import ApprovalAction
from apps.composer.models import Post
from apps.settings_manager.helpers import get_setting


@pytest.fixture
def reviewer(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def social_account(db, workspace):
    """A CONNECTED mock SocialAccount tied to ``workspace``.

    Mirrors the SocialAccount construction used by
    ``apps/publisher/tests/test_joseph_gate.py`` and the root
    ``due_platform_post_factory`` so PlatformPosts built in these tests sit
    behind a real provider account (the publish engine's
    ``_dispatch_to_provider`` and ``email_post_copy`` both read
    ``pp.social_account``).
    """
    from apps.social_accounts.models import SocialAccount

    return SocialAccount.objects.create(
        workspace=workspace,
        platform="mock",
        account_platform_id="acct-approvals-mock",
        account_name="mock approvals",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )


@pytest.mark.django_db
def test_review_copy_email_default(workspace):
    # Falls back to the app default when no workspace/org override exists.
    assert get_setting(workspace.id, "review.copy_email") == "martin.maina@africacen.org"


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
    assert len(mail.outbox) == 0            # no copy email leaked


@pytest.mark.django_db
def test_gate_still_blocks_after_send(workspace, reviewer, social_account):
    """Send approves + schedules the platform post, but the compliance gate at
    the provider chokepoint remains authoritative: an AI-drafted PlatformPost
    with no ``gate_id`` (and ``gate_bypassed=False``) is still blocked at
    publish time — Send does NOT bypass the gate.

    The gate is exercised exactly the way ``apps/publisher/tests/test_joseph_gate.py``
    drives it: instantiate the engine with ``PublishEngine.__new__`` and call
    ``_dispatch_to_provider`` directly (no Celery, no network, no live provider
    credentials). For an unapproved post the engine raises ``GateBlockError``
    BEFORE it ever resolves credentials or reaches a provider.
    """
    from apps.composer.models import PlatformPost
    from apps.approvals.send_actions import send_for_publish
    from apps.publisher.engine import GateBlockError, PublishEngine

    post = Post.objects.create(workspace=workspace, title="P",
        caption="Gate must remain.", review_state="pending",
        review_assignee=reviewer)
    pp = PlatformPost.objects.create(
        post=post,
        social_account=social_account,
        status=PlatformPost.Status.PENDING_REVIEW,
    )
    # Sanity: this is an AI-path post the gate is meant to block — no gate_id,
    # gate not bypassed. (gate_bypassed=True would be the human-authored path.)
    assert pp.gate_id is None
    assert pp.gate_bypassed is False

    send_for_publish(post, reviewer)

    post.refresh_from_db()
    assert post.review_state == "approved"
    assert post.scheduled_at is not None

    # Send scheduled the platform post (pending_review -> approved -> scheduled).
    pp.refresh_from_db()
    assert pp.status == "scheduled"

    # The gate is authoritative: invoking the engine's dispatch chokepoint on
    # the scheduled-but-unapproved post raises GateBlockError and never reaches
    # a provider. This assertion ALWAYS executes (no empty loop).
    engine = PublishEngine.__new__(PublishEngine)
    with pytest.raises(GateBlockError):
        engine._dispatch_to_provider(pp)

    # The block is terminal: the post was failed, never published.
    pp.refresh_from_db()
    assert pp.status != "published"
    assert pp.status == "failed"
    assert "GATE BLOCK" in (pp.publish_error or "")


@pytest.mark.django_db
def test_send_button_renders_in_queue(client, workspace, reviewer):
    Post.objects.create(workspace=workspace, title="Mine", caption="c",
        review_assignee=reviewer, review_state="pending")
    resp = client.get(reverse("console:approvals"))
    assert resp.status_code == 200
    assert b'value="send"' in resp.content
