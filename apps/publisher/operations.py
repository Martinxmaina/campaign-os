"""Post-publish operations: delete and edit (delete-recreate) for live posts.

LinkedIn (and several other networks) expose a delete endpoint but no edit
endpoint, so editing a published post is implemented as delete-then-recreate.
These operations are kept out of the scheduled publish engine so the composer
view — and any future API surface — can reuse the exact same orchestration
without dragging in the poll/retry machinery.

Credential resolution and provider lookup reuse the publish path
(``_resolve_publish_credentials`` + ``get_provider``) so per-org credentials,
env fallback and federation metadata behave identically to a fresh publish.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from providers import get_provider
from providers.types import PublishContent, PublishResult, PostType

from .engine import _resolve_publish_credentials

logger = logging.getLogger(__name__)


def _provider_for(platform_post):
    """Resolve (provider, access_token) for the platform_post's account."""
    account = platform_post.social_account
    credentials = _resolve_publish_credentials(account)
    provider = get_provider(account.platform, credentials)
    return provider, account.oauth_access_token


def delete_published_post(platform_post) -> bool:
    """Delete an already-published PlatformPost on its platform.

    Calls the provider's ``delete_post`` for the stored ``platform_post_id``,
    then marks the PlatformPost as no longer live: status returns to ``draft``
    and ``platform_post_id``/``published_at`` are cleared. The provider error
    (e.g. ``PublishError``) propagates so the caller can report failure and the
    live post is left untouched.
    """
    from apps.composer.models import PlatformPost

    platform_post_id = platform_post.platform_post_id
    if not platform_post_id:
        raise ValueError("PlatformPost has no platform_post_id to delete.")

    provider, access_token = _provider_for(platform_post)
    provider.delete_post(access_token, platform_post_id)

    # Provider delete succeeded — record that the post is no longer live.
    platform_post.status = PlatformPost.Status.DRAFT
    platform_post.platform_post_id = ""
    platform_post.published_at = None
    platform_post.save(
        update_fields=["status", "platform_post_id", "published_at", "updated_at"]
    )
    logger.info("Deleted published post %s (%s)", platform_post.id, platform_post_id)
    return True


def edit_published_post(platform_post, new_caption: str) -> PublishResult:
    """Edit a published PlatformPost via delete-then-recreate.

    LinkedIn has no edit endpoint, so we delete the live post, update the
    caption override, and re-publish. The PlatformPost's ``platform_post_id`` is
    replaced with the freshly-created post's id. The delete failure (if any)
    propagates before any state is mutated; a re-publish failure leaves the
    PlatformPost with the new caption but cleared platform id (it is no longer
    live), matching the engine's "failed publish" semantics.
    """
    from apps.composer.models import PlatformPost

    provider, access_token = _provider_for(platform_post)

    old_post_id = platform_post.platform_post_id
    if old_post_id:
        provider.delete_post(access_token, old_post_id)

    # Persist the new caption as the platform-specific override so
    # effective_caption reflects the edit.
    platform_post.platform_specific_caption = new_caption
    platform_post.platform_post_id = ""
    platform_post.published_at = None
    platform_post.status = PlatformPost.Status.PUBLISHING
    platform_post.save(
        update_fields=[
            "platform_specific_caption",
            "platform_post_id",
            "published_at",
            "status",
            "updated_at",
        ]
    )

    content = PublishContent(
        text=platform_post.effective_caption or "",
        title=platform_post.effective_title,
        description=platform_post.effective_caption,
        first_comment=platform_post.effective_first_comment,
        post_type=PostType.TEXT,
        extra=dict(platform_post.platform_extra or {}),
    )
    result = provider.publish_post(access_token, content)

    platform_post.platform_post_id = result.platform_post_id
    platform_post.status = PlatformPost.Status.PUBLISHED
    platform_post.published_at = timezone.now()
    platform_post.save(
        update_fields=["platform_post_id", "status", "published_at", "updated_at"]
    )
    logger.info(
        "Edited (delete-recreate) post %s: %s -> %s",
        platform_post.id,
        old_post_id,
        result.platform_post_id,
    )
    return result
