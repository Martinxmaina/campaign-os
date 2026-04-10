"""Composer service helpers."""

from __future__ import annotations


def sync_post_scheduled_at(post):
    """Set ``post.scheduled_at`` to ``min(children scheduled_at)``.

    Keeps the legacy ``Post.scheduled_at`` column in sync with the earliest
    per-platform scheduled time so listings, grouping and Coalesce fallbacks
    remain consistent. No-op when no PlatformPost has a scheduled_at set.
    """
    times = list(post.platform_posts.exclude(scheduled_at__isnull=True).values_list("scheduled_at", flat=True))
    if not times:
        return
    earliest = min(times)
    if post.scheduled_at != earliest:
        post.scheduled_at = earliest
        post.save(update_fields=["scheduled_at", "updated_at"])
