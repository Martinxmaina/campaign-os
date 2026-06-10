# apps/approvals/intake_publish.py
"""Create a publishable Django Post from an approved HERALD content item."""
from __future__ import annotations

import logging

from apps.composer.models import Post, PlatformPost
from apps.social_accounts.models import SocialAccount

logger = logging.getLogger(__name__)


def create_post_from_content(content: dict, intake) -> Post:
    """Build a Post (+ PlatformPosts for matching connected accounts) from a
    HERALD content item dict and its originating ContentIntake.

    If no SocialAccount matches a channel target, the Post is created without
    PlatformPosts (draft-only) so it is ready once the channel is connected.
    """
    body = str(content.get("body", "")).strip()
    title = str(content.get("title", "") or intake.angle)[:255]

    post = Post.objects.create(
        workspace=intake.workspace,
        title=title,
        caption=body,
    )

    # Match channel targets to connected SocialAccounts in this workspace.
    targets = intake.channel_targets or []
    wanted_platforms = {t.get("platform") for t in targets if t.get("platform")}
    for account in SocialAccount.objects.filter(
        workspace=intake.workspace, platform__in=wanted_platforms
    ):
        PlatformPost.objects.create(
            post=post,
            social_account=account,
            status=PlatformPost.Status.DRAFT,
        )

    intake.post = post
    intake.save(update_fields=["post", "updated_at"])
    return post
