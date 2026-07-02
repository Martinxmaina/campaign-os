"""Platform-aware metric catalog and engagement-rate derivation rules.

This is the single source of truth for which metrics each platform exposes
and how to label/format them in the UI. The shape of ``PLATFORM_METRICS``
mirrors the design's ``analytics/data.js``.
"""

from __future__ import annotations

# Kinds drive formatting (count vs percent vs minutes) in templates.
METRICS: dict[str, dict[str, str]] = {
    "impressions": {"label": "Impressions", "kind": "count"},
    "reach": {"label": "Reach", "kind": "count"},
    "views": {"label": "Views", "kind": "count"},
    "plays": {"label": "Plays", "kind": "count"},
    "likes": {"label": "Likes", "kind": "count"},
    "reactions": {"label": "Reactions", "kind": "count"},
    "comments": {"label": "Comments", "kind": "count"},
    "replies": {"label": "Replies", "kind": "count"},
    "shares": {"label": "Shares", "kind": "count"},
    "reposts": {"label": "Reposts", "kind": "count"},
    "saves": {"label": "Saves", "kind": "count"},
    "clicks": {"label": "Link clicks", "kind": "count"},
    "opens": {"label": "Email opens", "kind": "count"},
    "outbound": {"label": "Outbound clicks", "kind": "count"},
    "profile_visits": {"label": "Profile visits", "kind": "count"},
    "follows": {"label": "New follows", "kind": "count"},
    # Cumulative lifetime totals: each daily snapshot is the running audience
    # size, NOT a per-day increment — so the card value is the LATEST snapshot,
    # never the SUM over the window (summing showed Ghost 2622 = 2 × 1311).
    "followers": {"label": "Followers", "kind": "total"},
    "subscribers": {"label": "Subscribers", "kind": "total"},
    "watch_time": {"label": "Watch time", "kind": "minutes"},
    "avg_view_pct": {"label": "Avg view %", "kind": "percent"},
    "engagement": {"label": "Engagement rate", "kind": "percent"},
}

# Metrics that exist for the account/channel but never per individual post
# (you can't attribute new followers to one post via the platform APIs).
# These appear in account summaries but not in the per-post table.
ACCOUNT_ONLY: set[str] = {"follows", "followers", "subscribers"}

# Which metrics each platform's API reports (after the scope upgrades in the
# plan are in place). Verified against each platform's published insights API.
PLATFORM_METRICS: dict[str, list[str]] = {
    # IG media insights: reach, views (replaced impressions Apr-2025), likes,
    # comments, saved, shares, total_interactions; follower growth at account level.
    "instagram": ["reach", "views", "likes", "comments", "saves", "shares", "follows", "engagement"],
    "instagram_login": ["reach", "views", "likes", "comments", "saves", "shares", "follows", "engagement"],
    # FB post insights: impressions, reach (unique), reactions, comments, shares, clicks.
    "facebook": ["impressions", "reach", "reactions", "comments", "shares", "clicks", "follows", "engagement"],
    # LinkedIn share statistics: impressions, reactions, comments, reposts, clicks, engagement.
    # ``followers`` (lifetime total) comes from networkSizes.firstDegreeSize —
    # account-only, same lifetime-snapshot semantics as TikTok (no per-day
    # delta), so it surfaces the total rather than ``follows`` (new/day).
    "linkedin_company": ["impressions", "reactions", "comments", "reposts", "clicks", "follows", "followers", "engagement"],
    # LinkedIn Personal: only socialActions counts (no impressions/reach per API).
    "linkedin_personal": ["likes", "comments", "shares"],
    # YouTube Analytics: views, watch_time, avg_view_pct, likes, comments, shares, subscribers gained.
    "youtube": ["views", "watch_time", "avg_view_pct", "likes", "comments", "shares", "subscribers"],
    # TikTok video metrics: view/like/comment/share counts from /v2/video/query/.
    # ``followers`` (total) is account-only — TikTok's /v2/user/info/ returns
    # cumulative counters with no daily delta, so we surface the total rather
    # than ``follows`` (which is defined as "new follows" per day). watch_time
    # is intentionally absent: /v2/video/query/ doesn't expose it per-video
    # and TikTok has no public per-video Analytics-style endpoint yet — listing
    # it would render an always-zero chart and mislead users.
    "tiktok": ["views", "likes", "comments", "shares", "followers", "engagement"],
    # Bluesky / AT Protocol post aggregates: like, repost, reply counts (no impressions/views).
    "bluesky": ["likes", "reposts", "replies", "follows"],
    # Threads insights: views, likes, replies, reposts; account follower growth.
    "threads": ["views", "likes", "replies", "reposts", "follows"],
    # Pinterest pin analytics: impressions, saves, pin clicks, outbound clicks, engagement.
    "pinterest": ["impressions", "saves", "clicks", "outbound", "engagement"],
    # Google Business Profile performance: search/map impressions, clicks, calls, directions.
    "google_business": ["impressions", "clicks"],
    # Mastodon: only favourites/reblogs/replies from the public status record.
    "mastodon": ["likes", "reposts", "replies"],
    # Ghost (Nexus Brief): the Admin API exposes the member total
    # (meta.pagination.total) but no per-post or per-day engagement metrics,
    # so the only surface is the subscriber count (label "Subscribers").
    # Ghost: newsletter reach (recipients) + opens exist for EMAILED posts;
    # link clicks exist for all posts; subscribers is the account total.
    "ghost": ["reach", "opens", "clicks", "subscribers"],
    # Blotato add-on family: metrics from GET /v2/posts/{id}/analytics.
    # Each sub-platform exposes the same analytics response shape; the metric
    # list mirrors what the target network actually surfaces through Blotato.
    "blotato_instagram": ["impressions", "reach", "views", "likes", "comments", "saves", "shares", "clicks", "engagement"],
    "blotato_facebook": ["impressions", "reach", "likes", "comments", "shares", "clicks", "engagement"],
    "blotato_twitter": ["impressions", "reach", "likes", "comments", "shares", "clicks", "engagement"],
    "blotato_linkedin": ["impressions", "likes", "comments", "shares", "clicks", "engagement"],
    "blotato_threads": ["impressions", "reach", "views", "likes", "comments", "shares", "engagement"],
    "blotato_bluesky": ["likes", "comments", "shares"],
}

# The "hero" metric each platform defaults the big chart and table sort to.
PLATFORM_PRIMARY: dict[str, str] = {
    "instagram": "reach",
    "instagram_login": "reach",
    "facebook": "reach",
    "linkedin_company": "impressions",
    "linkedin_personal": "likes",
    "youtube": "views",
    "tiktok": "views",
    "bluesky": "likes",
    "threads": "views",
    "pinterest": "impressions",
    "google_business": "impressions",
    "mastodon": "likes",
    "ghost": "subscribers",
    # Blotato add-on family
    "blotato_instagram": "impressions",
    "blotato_facebook": "impressions",
    "blotato_twitter": "impressions",
    "blotato_linkedin": "impressions",
    "blotato_threads": "impressions",
    "blotato_bluesky": "likes",
}

# Brand-orange override for charts; per-platform colors used as a tweak.
PLATFORM_COLOR: dict[str, str] = {
    "instagram": "#E4405F",
    "instagram_login": "#E4405F",
    "facebook": "#1877F2",
    "linkedin_personal": "#0A66C2",
    "linkedin_company": "#0A66C2",
    "youtube": "#FF0000",
    "tiktok": "#111111",
    "bluesky": "#0085FF",
    "threads": "#111111",
    "pinterest": "#BD081C",
    "google_business": "#4285F4",
    "mastodon": "#6364FF",
    "ghost": "#15171A",
    # Blotato add-on family — use the target network's canonical color.
    "blotato_instagram": "#E4405F",
    "blotato_facebook": "#1877F2",
    "blotato_twitter": "#111111",
    "blotato_linkedin": "#0A66C2",
    "blotato_threads": "#111111",
    "blotato_bluesky": "#0085FF",
}

# Metrics that contribute to engagement rate (numerator).
ENGAGEMENT_PARTS: list[str] = [
    "likes",
    "reactions",
    "comments",
    "replies",
    "shares",
    "reposts",
    "saves",
    "clicks",
    "outbound",
]

# Candidate denominators in priority order (first match wins). If none of
# these exist on the platform, the engagement card is suppressed in the UI.
ENGAGEMENT_DENOMINATORS: list[str] = ["reach", "impressions", "views", "plays"]


def post_metrics_for(platform: str) -> list[str]:
    """Metrics that show up in per-post views (table columns, detail drawer).

    Account-only metrics (follows, subscribers) are filtered out — you can't
    attribute them to a single post.
    """
    return [m for m in PLATFORM_METRICS.get(platform, []) if m not in ACCOUNT_ONLY]


def hero_card_metrics(platform: str) -> list[str]:
    """Top-line "reach-like" metrics that get their own StatCard in the hero row.

    Engagement components and the rate itself live in the EngagementCard, and
    account-only growth metrics live in the header — so neither shows up here.
    """
    return [
        m
        for m in PLATFORM_METRICS.get(platform, [])
        if m not in ENGAGEMENT_PARTS and m != "engagement" and m not in ACCOUNT_ONLY
    ]


def has_engagement_card(platform: str) -> bool:
    """True if the platform has both engagement parts AND a reach-like denom.

    Bluesky/Mastodon/LinkedIn-Personal have no reach denom, so we render
    only count cards for them (per the plan's "hard platform gap" handling).
    """
    metrics = PLATFORM_METRICS.get(platform, [])
    has_parts = any(p in metrics for p in ENGAGEMENT_PARTS)
    has_denom = any(d in metrics for d in ENGAGEMENT_DENOMINATORS)
    return has_parts and has_denom
