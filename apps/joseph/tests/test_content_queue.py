"""Tests for Joseph's personal content queue at /joseph/content/.

The queue lists Posts assigned to / authored by Joseph (his review queue),
newest publish-date first. A post whose gate blocked a platform variant shows
the gate findings inline with an audited "Override (logged)" action — overriding
writes an ``ApprovalAction`` audit record and moves ``review_state`` to APPROVED
(an override is logged, not a silent unblock). A "Draft new" action links to the
composer carrying ``voice_user=joseph`` so HERALD drafts in Joseph's voice.

The view is gated by ``_can_access_joseph`` and degrades gracefully (it reads
only Django data, so there is no agent dependency to 500 on). CSP-safe: the
override is an hx-post / POST form, no inline onclick/onsubmit.
"""
import pytest
from django.urls import reverse


@pytest.fixture
def joseph(client, org_owner, workspace):
    """Joseph = an owner of the workspace (can access the principal surface)."""
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def viewer(client, db, organization, workspace):
    """An ordinary workspace member (viewer) — must not reach Joseph's content queue."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer", tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


def _post_for(joseph, workspace, *, title="Joseph post", review_state="pending", scheduled_at=None):
    from apps.composer.models import Post
    return Post.objects.create(
        workspace=workspace, author=joseph, review_assignee=joseph,
        title=title, caption=f"{title} caption",
        review_state=review_state, scheduled_at=scheduled_at,
    )


def _flag_post(post, *, platform="mock", reason="partner-separation"):
    """Attach a gate-blocked PlatformPost (failed + GATE BLOCK) to a Post."""
    from apps.composer.models import PlatformPost
    from apps.social_accounts.models import SocialAccount
    account = SocialAccount.objects.create(
        workspace=post.workspace, platform=platform,
        account_platform_id=f"acct-{platform}-{post.id}", account_name=f"{platform} acct",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    return PlatformPost.objects.create(
        post=post, social_account=account,
        status=PlatformPost.Status.FAILED,
        publish_error=f"GATE BLOCK: {reason}",
    )


# --------------------------------------------------------------------------
# listing
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_content_queue_renders_for_joseph(joseph, client, workspace):
    _post_for(joseph, workspace, title="LinkedIn AI 10Bn")
    resp = client.get(reverse("joseph:content"))
    assert resp.status_code == 200
    assert b"LinkedIn AI 10Bn" in resp.content


@pytest.mark.django_db
def test_content_queue_lists_only_josephs_posts(joseph, client, workspace, organization):
    """Only posts assigned to / authored by Joseph appear — not other people's."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.composer.models import Post
    other = User.objects.create_user(
        email="someone@example.com", password="x", name="Someone", tos_accepted_at=timezone.now())
    Post.objects.create(workspace=workspace, author=other, title="NotJosephPost", caption="x")
    _post_for(joseph, workspace, title="JosephOwnPost")

    resp = client.get(reverse("joseph:content"))
    assert b"JosephOwnPost" in resp.content
    assert b"NotJosephPost" not in resp.content


@pytest.mark.django_db
def test_content_queue_sorted_by_publish_date(joseph, client, workspace):
    """Posts are ordered by publish date (soonest/most-recent scheduling first)."""
    from datetime import timedelta

    from django.utils import timezone
    now = timezone.now()
    _post_for(joseph, workspace, title="Older slot", scheduled_at=now - timedelta(days=2))
    _post_for(joseph, workspace, title="Newer slot", scheduled_at=now + timedelta(days=1))
    resp = client.get(reverse("joseph:content"))
    body = resp.content.decode()
    assert body.index("Newer slot") < body.index("Older slot")


@pytest.mark.django_db
def test_content_queue_shows_gate_findings_and_override(joseph, client, workspace):
    """A flagged post shows the gate findings + an 'Override (logged)' action."""
    post = _post_for(joseph, workspace, title="Flagged post")
    _flag_post(post, reason="partner-separation")
    resp = client.get(reverse("joseph:content"))
    body = resp.content
    assert b"partner-separation" in body
    assert b"Override" in body
    # the override action targets this post
    assert reverse("joseph:content-override", args=[post.id]).encode() in body


@pytest.mark.django_db
def test_content_queue_draft_link_carries_voice(joseph, client, workspace):
    """The 'Draft new' action links to the composer with voice_user=joseph."""
    resp = client.get(reverse("joseph:content"))
    body = resp.content
    assert b"voice_user=joseph" in body
    assert reverse("composer:compose", kwargs={"workspace_id": workspace.id}).encode() in body


@pytest.mark.django_db
def test_content_queue_forbidden_for_viewer(viewer, client):
    resp = client.get(reverse("joseph:content"))
    assert resp.status_code in (403, 302)


@pytest.mark.django_db
def test_content_queue_csp_safe_no_inline_handlers(joseph, client, workspace):
    post = _post_for(joseph, workspace, title="Flagged")
    _flag_post(post)
    resp = client.get(reverse("joseph:content"))
    body = resp.content
    assert b"onclick=" not in body
    assert b"onsubmit=" not in body


# --------------------------------------------------------------------------
# override (POST → audit + review_state)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_override_writes_audit_and_sets_state(joseph, client, workspace):
    """Overriding a gate finding writes an ApprovalAction audit record and moves
    the post's review_state to APPROVED (override is logged, not silent)."""
    from apps.approvals.models import ApprovalAction
    from apps.composer.models import Post
    post = _post_for(joseph, workspace, title="Flagged", review_state="pending")
    _flag_post(post, reason="partner-separation")

    resp = client.post(reverse("joseph:content-override", args=[post.id]))
    assert resp.status_code in (200, 302, 303)

    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.APPROVED
    audit = ApprovalAction.objects.filter(post=post, user=joseph)
    assert audit.exists()
    # the audit record records who overrode and that it was an override
    action = audit.first()
    assert action.action == ApprovalAction.ActionType.APPROVED
    assert "override" in action.comment.lower()


@pytest.mark.django_db
def test_override_forbidden_for_viewer(viewer, client, workspace, organization):
    from apps.accounts.models import User  # noqa: F401
    from apps.approvals.models import ApprovalAction
    from apps.composer.models import Post
    post = Post.objects.create(workspace=workspace, title="x", caption="x")
    resp = client.post(reverse("joseph:content-override", args=[post.id]))
    assert resp.status_code in (403, 302)
    assert not ApprovalAction.objects.filter(post=post).exists()


@pytest.mark.django_db
def test_override_requires_post(joseph, client, workspace):
    """The override endpoint rejects GET (state-changing → POST only)."""
    post = _post_for(joseph, workspace, title="Flagged")
    resp = client.get(reverse("joseph:content-override", args=[post.id]))
    assert resp.status_code in (405, 403, 302)
