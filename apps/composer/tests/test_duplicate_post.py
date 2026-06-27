"""Duplicate-post action — clone caption + assets + channel targets into a fresh draft."""
import pytest
from django.urls import reverse

from apps.composer.models import PlatformPost, Post, PostMedia
from apps.members.models import WorkspaceMembership
from apps.social_accounts.models import SocialAccount

pytestmark = pytest.mark.django_db


def _media_asset(workspace):
    from apps.media_library.models import MediaAsset

    return MediaAsset.objects.create(
        organization=workspace.organization, workspace=workspace,
        media_type="image", file="x.png", filename="x.png",
    )


def test_duplicate_clones_content_media_and_channels(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)

    src = Post.objects.create(
        workspace=workspace, author=user, title="Launch", caption="Hello world",
        first_comment="first!", tags=["ai", "energy"], campaign="EGM",
    )
    asset = _media_asset(workspace)
    PostMedia.objects.create(post=src, media_asset=asset, position=0, alt_text="card")
    acct = SocialAccount.objects.create(
        workspace=workspace, platform="blotato_linkedin", account_platform_id="dup-1", account_name="WAIIS LI"
    )
    PlatformPost.objects.create(
        post=src, social_account=acct, platform_specific_caption="LI variant",
        status=PlatformPost.Status.PUBLISHED, platform_post_id="ext-123",
    )

    resp = client.post(reverse("composer:duplicate_post", kwargs={"workspace_id": workspace.id, "post_id": src.id}))
    assert resp.status_code in (200, 204, 302)

    clones = Post.objects.filter(workspace=workspace).exclude(id=src.id)
    assert clones.count() == 1
    clone = clones.first()

    # Content copied
    assert clone.caption == "Hello world"
    assert clone.first_comment == "first!"
    assert clone.tags == ["ai", "energy"]
    assert clone.campaign == "EGM"
    assert clone.title == "Copy of Launch"
    assert clone.review_state == Post.ReviewState.NONE
    assert clone.id != src.id

    # Media copied (same asset, new row)
    assert clone.media_attachments.count() == 1
    assert clone.media_attachments.first().media_asset_id == asset.id

    # Channel target copied, but publishing state RESET to a clean draft
    assert clone.platform_posts.count() == 1
    cpp = clone.platform_posts.first()
    assert cpp.social_account_id == acct.id
    assert cpp.platform_specific_caption == "LI variant"
    assert cpp.status == PlatformPost.Status.DRAFT
    assert cpp.platform_post_id == ""
    assert cpp.published_at is None
