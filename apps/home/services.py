"""Pure data builders for the role-aware Home. No request/template logic here."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.analytics.models import PostInsightsSnapshot
from apps.composer.models import PlatformPost

# Headline metric for the Home graph + the reach total shown beside it.
_GRAPH_METRIC = "engagement"
_REACH_METRIC = "reach"


def _published_platform_post_ids(workspace):
    """PlatformPosts that went out THROUGH Campaign OS for this workspace."""
    return PlatformPost.objects.filter(
        post__workspace_id=workspace.id,
        status=PlatformPost.Status.PUBLISHED,
    )


def performance_summary(workspace, days: int = 30, metric: str = _GRAPH_METRIC) -> dict:
    """Daily series + headline numbers for posts published via the platform.

    Returns a dict the template renders directly:
      series:          list[float], one bucket per day (oldest -> newest)
      labels:          list[str] ISO dates aligned with `series`
      metric_label:    human label for the series
      posts_published: count of PlatformPosts published in the window
      total_reach:     summed reach over the window
      avg_engagement:  mean of non-zero series buckets (0 if none)
      by_platform:     list[{platform, value}] engagement totals per platform
      has_data:        bool — drives the empty state
      window_days:     echoes `days`
    """
    end = timezone.now().date()
    start = end - timedelta(days=days - 1)

    pp = _published_platform_post_ids(workspace)
    pp_ids = list(pp.values_list("id", flat=True))

    # Daily engagement series (summed across all the workspace's published posts).
    by_date = {}
    if pp_ids:
        rows = (
            PostInsightsSnapshot.objects.filter(
                platform_post_id__in=pp_ids, metric_key=metric,
                date__gte=start, date__lte=end,
            )
            .values("date")
            .annotate(value=Sum("value"))
        )
        by_date = {r["date"]: float(r["value"] or 0.0) for r in rows}

    series = [by_date.get(start + timedelta(days=i), 0.0) for i in range(days)]
    labels = [(start + timedelta(days=i)).isoformat() for i in range(days)]

    posts_published = pp.filter(
        published_at__date__gte=start, published_at__date__lte=end
    ).count()

    total_reach = 0.0
    by_platform: list[dict] = []
    if pp_ids:
        total_reach = float(
            PostInsightsSnapshot.objects.filter(
                platform_post_id__in=pp_ids, metric_key=_REACH_METRIC,
                date__gte=start, date__lte=end,
            ).aggregate(t=Sum("value"))["t"]
            or 0.0
        )
        plat_rows = (
            PostInsightsSnapshot.objects.filter(
                platform_post_id__in=pp_ids, metric_key=metric,
                date__gte=start, date__lte=end,
            )
            .values("platform_post__social_account__platform")
            .annotate(value=Sum("value"))
            .order_by("-value")
        )
        by_platform = [
            {"platform": r["platform_post__social_account__platform"], "value": float(r["value"] or 0.0)}
            for r in plat_rows
            if r["platform_post__social_account__platform"]
        ]

    nonzero = [v for v in series if v]
    avg_engagement = round(sum(nonzero) / len(nonzero), 1) if nonzero else 0.0
    has_data = posts_published > 0 or any(series)

    # Pre-compute the SVG bar geometry here so the template stays logic-free.
    # Each bar is normalised to a 70px-tall plot; ``y`` is the top edge.
    _peak = max(series) or 1.0
    bar_heights = [
        {"h": round(70 * v / _peak, 2), "y": round(70 - 70 * v / _peak, 2)}
        for v in series
    ]

    return {
        "series": series,
        "labels": labels,
        "metric_label": "Engagement",
        "posts_published": posts_published,
        "total_reach": total_reach,
        "avg_engagement": avg_engagement,
        "by_platform": by_platform,
        "has_data": has_data,
        "window_days": days,
        "bar_heights": bar_heights,
    }


# ----------------------------------------------------------------------------
# Action-card builders (sign-off, drafts, going-out-soon)
#
# NOTE on field names: a Post's editorial status is *derived* from its
# ``platform_posts`` children (``apps.composer.status.derive_post_status``); it
# is not a settable ``Post`` column. So "draft" is queried via the child
# ``platform_posts__status`` join — mirroring ``apps/composer/views.drafts_list``
# (composer/views.py:~1563) — NOT via a ``review_state`` literal. ``review_state``
# is the separate AI-approval column whose values are
# none/pending/approved/changes_requested/rejected (see Post.ReviewState), used
# only by ``pending_signoff``. ``scheduled_at`` is a real ``Post`` field.
# ----------------------------------------------------------------------------
from apps.composer.models import Post

# Child statuses that mean a post has moved past "draft".
_BEYOND_DRAFT = [
    "pending_review",
    "pending_client",
    "approved",
    "scheduled",
    "publishing",
    "partially_published",
    "published",
    "failed",
]


def my_drafts(workspace, user, limit: int = 6):
    """This user's draft posts in this workspace, newest first.

    A post is a draft when a PlatformPost child is in the ``draft`` state and
    none have advanced further (matches ``composer.views.drafts_list``).
    """
    return list(
        Post.objects.filter(
            workspace_id=workspace.id, author=user, platform_posts__status="draft"
        )
        .exclude(platform_posts__status__in=_BEYOND_DRAFT)
        .distinct()
        .order_by("-updated_at")[:limit]
    )


def going_out_soon(workspace, days: int = 7, limit: int = 6):
    """Posts scheduled to publish in the next ``days`` days, soonest first."""
    now = timezone.now()
    return list(
        Post.objects.filter(
            workspace_id=workspace.id,
            scheduled_at__gte=now,
            scheduled_at__lte=now + timedelta(days=days),
        )
        .distinct()
        .order_by("scheduled_at")[:limit]
    )


def pending_signoff(workspace, user, limit: int = 6):
    """Posts awaiting review that this user can act on (reviewer or approver)."""
    qs = Post.objects.filter(
        workspace_id=workspace.id, review_state=Post.ReviewState.PENDING
    ).order_by("-updated_at")
    return list(qs[:limit])
