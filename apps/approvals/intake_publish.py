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

    Idempotent: if this intake already has a linked Post (re-approval, or any
    re-fire of approval_decide), return the existing Post rather than creating a
    second one and silently orphaning the first.
    """
    if intake.post_id:
        return intake.post

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


def ensure_post_from_content_item(content: dict, workspace, author=None) -> Post:
    """Materialise a Django Post from a standalone HERALD content item dict.

    Unlike ``create_post_from_content`` (which is keyed to a ``ContentIntake``),
    this bridges a console ``/content/items`` draft that has no intake row, so
    the Drafts surface can publish/schedule/edit it through the real composer +
    publish gate. Idempotent: the originating content id is recorded as a
    ``herald:<id>`` tag, so re-firing returns the same Post rather than spawning
    duplicates. Creates a DRAFT PlatformPost for every connected account in the
    workspace (none → a draft-only Post, ready once a channel is connected).
    """
    content_id = str(content.get("id") or "").strip()
    tag = f"herald:{content_id}" if content_id else ""
    if tag:
        existing = Post.objects.filter(workspace=workspace, tags__contains=[tag]).first()
        if existing is not None:
            return existing

    body = str(content.get("body", "")).strip()
    title = str(content.get("title", "") or "")[:255]
    post = Post.objects.create(
        workspace=workspace,
        author=author,
        title=title,
        caption=body,
        track=str(content.get("track") or ""),
        tags=[tag] if tag else [],
    )
    for account in SocialAccount.objects.filter(
        workspace=workspace,
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    ):
        PlatformPost.objects.create(
            post=post,
            social_account=account,
            status=PlatformPost.Status.DRAFT,
        )
    return post
