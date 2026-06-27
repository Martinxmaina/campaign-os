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
    }
