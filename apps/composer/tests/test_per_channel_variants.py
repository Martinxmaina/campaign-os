"""Per-channel caption variants persist across an edit.

The save + publish sides already existed (override_caption_<id> ->
platform_specific_caption -> effective_caption). The gap was the edit page not
pre-filling the saved override, so a re-save wiped it. The view now ships the
saved overrides to the composer (composer-platform-overrides) for prefill.
"""
import pytest
from django.urls import reverse

from apps.composer.models import PlatformPost, Post
from apps.members.models import WorkspaceMembership
from apps.social_accounts.models import SocialAccount

pytestmark = pytest.mark.django_db


def _setup(workspace, user):
    post = Post.objects.create(workspace=workspace, author=user, caption="Shared caption")
    acct = SocialAccount.objects.create(
        workspace=workspace, platform="blotato_linkedin", account_platform_id="v-1", account_name="WAIIS LI"
    )
    pp = PlatformPost.objects.create(
        post=post, social_account=acct, platform_specific_caption="LinkedIn-only variant",
    )
    return post, acct, pp


def test_edit_page_ships_saved_override_for_prefill(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    post, acct, _ = _setup(workspace, user)

    resp = client.get(reverse("composer:compose_edit", kwargs={"workspace_id": workspace.id, "post_id": post.id}))
    assert resp.status_code == 200
    body = resp.content.decode()
    # The prefill blob + the saved variant must be present so the composer can
    # auto-open + pre-fill the per-channel override (instead of rendering empty).
    assert "composer-platform-overrides" in body
    assert "LinkedIn-only variant" in body


def test_resave_preserves_override(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    post, acct, pp = _setup(workspace, user)

    # Simulate the composer re-submitting the (now pre-filled) override.
    client.post(
        reverse("composer:save_post_edit", kwargs={"workspace_id": workspace.id, "post_id": post.id}),
        data={
            "action": "save_draft",
            "caption": "Shared caption",
            "tags": "",
            "selected_accounts": str(acct.id),
            f"override_caption_{acct.id}": "LinkedIn-only variant",
        },
    )
    pp.refresh_from_db()
    assert pp.platform_specific_caption == "LinkedIn-only variant"
    assert pp.effective_caption == "LinkedIn-only variant"
