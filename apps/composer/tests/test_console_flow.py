"""Console content flow made actionable: draft → submit → (approve) → publish,
plus HERALD draft-detail publish/schedule/edit. These close the gaps that made
'the flow not work' (drafts had no path forward)."""
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.composer.models import PlatformPost, Post


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return client


def _draft_post(workspace, author):
    from apps.social_accounts.models import SocialAccount
    acct = SocialAccount.objects.create(
        workspace=workspace, platform="linkedin", account_platform_id="li-x",
        account_name="AfCEN", connection_status=SocialAccount.ConnectionStatus.CONNECTED)
    post = Post.objects.create(workspace=workspace, author=author, caption="Fund the talent.")
    PlatformPost.objects.create(post=post, social_account=acct, status=PlatformPost.Status.DRAFT)
    return post


# ── Content Studio: the missing "Submit for review" step ────────────────────

@pytest.mark.django_db
def test_studio_submit_moves_draft_into_review(authed, workspace, org_owner):
    post = _draft_post(workspace, org_owner)
    assert post.status == "draft"  # derived
    resp = authed.post(reverse("console:studio-submit-review", args=[post.id]))
    assert resp.status_code == 302  # redirects back to the studio
    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.PENDING        # shows in AI Approvals
    assert post.review_assignee_id is not None                  # routed to a reviewer
    assert post.platform_posts.first().status == "pending_review"  # studio re-derives pending


@pytest.mark.django_db
def test_studio_card_renders_submit_for_a_draft(authed, workspace, org_owner):
    _draft_post(workspace, org_owner)
    resp = authed.get(reverse("console:content"))
    assert resp.status_code == 200
    assert b"Submit for review" in resp.content


# ── HERALD draft detail: publish / schedule / edit ──────────────────────────

CONTENT = {"id": "c-9", "title": "T", "body": "Body.", "track": "ai10bn"}


@pytest.mark.django_db
def test_draft_publish_success_redirects_with_message(authed):
    with patch("apps.composer.console_views.safe_get", return_value=CONTENT), \
         patch("apps.composer.console_publish.publish_content_item",
               return_value={"ok": True, "published": True, "accounts": 1, "post_id": "p1"}):
        resp = authed.post(reverse("console:draft-publish", args=["c-9"]))
    assert resp.status_code == 302


@pytest.mark.django_db
def test_draft_publish_gate_block_rerenders_with_findings(authed):
    blocked = {"ok": False, "reason": "gate_blocked", "verdict": "block",
               "findings": [{"msg": "unverified claim"}], "post_id": "p1"}
    with patch("apps.composer.console_views.safe_get", return_value=CONTENT), \
         patch("apps.composer.console_publish.publish_content_item", return_value=blocked):
        resp = authed.post(reverse("console:draft-publish", args=["c-9"]))
    assert resp.status_code == 200
    assert b"blocked" in resp.content.lower()
    assert b"unverified claim" in resp.content


@pytest.mark.django_db
def test_draft_edit_materialises_post_and_redirects_to_composer(authed, workspace):
    with patch("apps.composer.console_views.safe_get", return_value=CONTENT):
        resp = authed.get(reverse("console:draft-edit", args=["c-9"]))
    assert resp.status_code == 302
    post = Post.objects.get(workspace=workspace, tags__contains=["herald:c-9"])
    assert f"/workspace/{workspace.id}/compose/{post.id}/" in resp.url
