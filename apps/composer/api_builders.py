"""Compose composer/content models into the reporting API schemas.

HTTP-agnostic: the router passes ``workspace`` and the key's allowlist; these
builders never touch ``request`` so the MCP transport can reuse them. Scoping
mirrors ``apps/api/routers/posts.py::_get_workspace_post`` — a post is visible
only if it has no platform children, or every child's account is allowlisted.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from apps.api.schemas import CampaignSummary, ContentItem, ContentPlatform
from apps.composer.models import Post
from apps.composer.status import derive_post_status

_CAPTION_PREVIEW = 160


def _scoped_posts(workspace):
    """Workspace posts with children + accounts prefetched, newest first."""
    return (
        Post.objects.filter(workspace_id=workspace.id)
        .select_related("intake_source")
        .prefetch_related("platform_posts__social_account")
        .order_by("-created_at", "id")
    )


def _visible_to_allowlist(post, allowed_account_ids: set[uuid.UUID]) -> bool:
    child_account_ids = {pp.social_account_id for pp in post.platform_posts.all()}
    if not child_account_ids:
        return True  # pure draft, targets no account → no confused-deputy risk
    return child_account_ids.issubset(allowed_account_ids)


def _has_intake(post) -> bool:
    """True when a ContentIntake row links to this Post (reverse OneToOne).

    ``Post.intake_source`` raises ``DoesNotExist`` when no row links back,
    so we can't use ``getattr(..., None)``. ``_scoped_posts`` select_related's
    the relation, so this is query-free in the hot path.
    """
    try:
        return post.intake_source is not None
    except ObjectDoesNotExist:
        return False


def _content_item(post) -> ContentItem:
    children = list(post.platform_posts.all())
    platforms = [
        ContentPlatform(
            platform=pp.social_account.platform,
            account_id=pp.social_account_id,
            status=pp.status,
            scheduled_at=pp.scheduled_at,
            published_at=pp.published_at,
            platform_post_id=pp.platform_post_id or "",
            error=pp.publish_error or "",
        )
        for pp in children
    ]
    return ContentItem(
        id=post.id,
        title=post.title,
        caption_preview=post.caption[:_CAPTION_PREVIEW],
        source="curated" if _has_intake(post) else "created",
        status=derive_post_status([pp.status for pp in children]),
        campaign=post.campaign,
        track=post.track,
        pillar=post.pillar,
        platforms=platforms,
        scheduled_at=post.scheduled_at,
        published_at=post.published_at,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def build_content_list(
    workspace,
    allowed_account_ids: set[uuid.UUID],
    *,
    status: str | None = None,
    campaign: str | None = None,
    platform: str | None = None,
    source: str | None = None,
    scheduled_after=None,
    scheduled_before=None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[ContentItem], bool]:
    """Return (page_items, has_more).

    DB filters: campaign, source, scheduled-date range, platform. The allowlist
    filter and the derived ``status`` filter run in Python because both depend
    on the post's set of children; the resulting full list is sliced for the
    offset cursor. Content volumes here are workspace-scoped
    (tens-to-hundreds), so full materialisation is acceptable.
    """
    qs = _scoped_posts(workspace)
    if campaign is not None:
        qs = qs.filter(campaign=campaign)
    if source == "curated":
        qs = qs.filter(intake_source__isnull=False)
    elif source == "created":
        qs = qs.filter(intake_source__isnull=True)
    if scheduled_after is not None:
        qs = qs.filter(scheduled_at__gte=scheduled_after)
    if scheduled_before is not None:
        qs = qs.filter(scheduled_at__lte=scheduled_before)
    if platform is not None:
        qs = qs.filter(platform_posts__social_account__platform=platform).distinct()

    visible = [p for p in qs if _visible_to_allowlist(p, allowed_account_ids)]
    items = [_content_item(p) for p in visible]
    if status is not None:
        items = [it for it in items if it.status == status]

    window = items[offset : offset + limit + 1]
    has_more = len(window) > limit
    return window[:limit], has_more


def build_content_summary(workspace, allowed_account_ids: set[uuid.UUID]) -> dict:
    """Counts + scheduling windows over allowlist-visible posts.

    Returns ``{total, by_status, scheduled_next_7d, published_last_30d}``.
    """
    now = timezone.now()
    soon = now + timedelta(days=7)
    last_30 = now - timedelta(days=30)

    posts = [p for p in _scoped_posts(workspace) if _visible_to_allowlist(p, allowed_account_ids)]

    by_status: dict[str, int] = {}
    scheduled_next_7d = 0
    published_last_30d = 0
    for post in posts:
        st = derive_post_status([pp.status for pp in post.platform_posts.all()])
        by_status[st] = by_status.get(st, 0) + 1
        if post.scheduled_at and now <= post.scheduled_at <= soon:
            scheduled_next_7d += 1
        if post.published_at and post.published_at >= last_30:
            published_last_30d += 1

    return {
        "total": len(posts),
        "by_status": by_status,
        "scheduled_next_7d": scheduled_next_7d,
        "published_last_30d": published_last_30d,
    }


def build_campaigns(
    workspace,
    allowed_account_ids: set[uuid.UUID],
    *,
    days: int = 30,
    account_map: dict | None = None,
    limit: int | None = None,
) -> list[CampaignSummary]:
    """Group allowlist-visible posts by their non-blank campaign string.

    ``account_map`` is an ``apps.analytics.api_builders.account_metric_map``
    result (or None to omit analytics). Per-campaign analytics are summed from
    that pre-computed map over the campaign's own accounts, so no extra
    analytics queries fire here. Sorted by most-recent activity; ``limit`` caps
    the count (None = all).
    """
    posts = [p for p in _scoped_posts(workspace) if _visible_to_allowlist(p, allowed_account_ids)]

    groups: dict[str, list] = {}
    for post in posts:
        name = (post.campaign or "").strip()
        if not name:
            continue
        groups.setdefault(name, []).append(post)

    summaries: list[CampaignSummary] = []
    for name, group in groups.items():
        by_status: dict[str, int] = {}
        platforms: set[str] = set()
        account_ids: set[uuid.UUID] = set()
        for post in group:
            children = list(post.platform_posts.all())
            st = derive_post_status([pp.status for pp in children])
            by_status[st] = by_status.get(st, 0) + 1
            for pp in children:
                platforms.add(pp.social_account.platform)
                account_ids.add(pp.social_account_id)
        created_times = [p.created_at for p in group]
        analytics = None
        if account_map is not None:
            from apps.analytics.api_builders import build_workspace_analytics_rollup

            scoped = {aid: account_map[aid] for aid in account_ids if aid in account_map}
            analytics = build_workspace_analytics_rollup(scoped, days)
        summaries.append(
            CampaignSummary(
                name=name,
                content_count=len(group),
                by_status=by_status,
                platforms=sorted(platforms),
                first_post=min(created_times),
                last_post=max(created_times),
                analytics=analytics,
            )
        )

    summaries.sort(key=lambda c: c.last_post or c.first_post, reverse=True)
    return summaries[:limit] if limit is not None else summaries
