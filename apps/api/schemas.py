"""Pydantic request/response shapes for the Agent API.

Kept small on purpose: agents will rely on the auto-generated OpenAPI
spec at ``/api/v1/docs``, so every field needs a sensible description.

We deliberately don't expose internal fields like ``workspace_id`` in
request bodies — workspace scope comes from the bearer token, never
from client-supplied JSON. This is the same confused-deputy defence
Postiz uses.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Literal

from ninja import Field, Schema
from pydantic import field_serializer

if TYPE_CHECKING:
    from apps.analytics.derive import DerivedMetric
    from apps.composer.models import PlatformPost, Post


def _serialize_utc_z(value: dt.datetime | None) -> str | None:
    """Render a datetime as ISO 8601 with a trailing ``Z`` for UTC.

    Pydantic's default datetime serialization emits ``+00:00`` for UTC,
    while Django's JSON encoder emits ``Z``. Without explicit normalization
    REST and MCP responses can disagree for the same instant.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------


class AccountSummary(Schema):
    id: uuid.UUID
    platform: str
    account_name: str
    account_handle: str = ""
    connection_status: str
    char_limit: int = Field(
        2200,
        description="Maximum caption length the platform accepts. Reject locally before calling /posts.",
    )
    needs_title: bool = Field(
        False,
        description="True when the platform requires a title (YouTube, Pinterest). When false, the title field is ignored.",
    )
    supports_first_comment: bool = Field(
        True,
        description=(
            "True when the platform can auto-post a first comment after publish. "
            "False for TikTok, Pinterest, Bluesky, Google Business. "
            "LinkedIn Personal returns false when authorized via OIDC instead of the Community Management API. "
            "If false, ``first_comment`` is silently dropped at publish time."
        ),
    )

    @classmethod
    def from_social_account(cls, sa) -> AccountSummary:
        return cls(
            id=sa.id,
            platform=sa.platform,
            account_name=sa.account_name,
            account_handle=getattr(sa, "account_handle", "") or "",
            connection_status=sa.connection_status,
            char_limit=sa.char_limit,
            needs_title=bool(sa.field_config.get("needs_title", False)),
            supports_first_comment=sa.supports_first_comment(),
        )


class StorageSummary(Schema):
    used_bytes: int
    limit_bytes: int
    remaining_bytes: int
    plan_slug: str = Field("", description="IntelligenceSubscription plan slug; empty if no active subscription.")


class MeResponse(Schema):
    """Echoes everything the key is scoped to so an agent can self-introspect."""

    api_key_id: uuid.UUID
    workspace_id: uuid.UUID
    workspace_name: str
    organization_id: uuid.UUID
    permissions: list[str]
    storage: StorageSummary
    allowlisted_accounts: list[AccountSummary]


# ---------------------------------------------------------------------------
# /accounts
# ---------------------------------------------------------------------------


class AccountsListResponse(Schema):
    accounts: list[AccountSummary]


# ---------------------------------------------------------------------------
# /posts — write
# ---------------------------------------------------------------------------


PostAction = Literal["draft", "schedule"]


class PlatformOverride(Schema):
    """Per-account override of the post's title/caption/first_comment.

    Mirrors the three form fields the cookie-authenticated UI accepts
    (see [apps/composer/views.py:85-96]). Maps to the model's
    ``platform_specific_*`` columns on ``PlatformPost``.

    Each field is independent: omit a field (or send ``null``) to keep
    the post's default for that platform. Send a string (including ``""``
    to explicitly blank out the value just for this platform) to apply
    the override.
    """

    social_account_id: uuid.UUID = Field(
        ...,
        description="Must reference an account that is a child of this post.",
    )
    title: str | None = Field(None, max_length=255)
    caption: str | None = Field(None, max_length=10_000)
    first_comment: str | None = Field(None, max_length=10_000)


class CreatePostRequest(Schema):
    """Create a draft or directly schedule a post against one account.

    ``social_account_id`` MUST be in the key's allowlist; the auth class
    raises 403 otherwise.
    """

    social_account_id: uuid.UUID = Field(
        ...,
        description="ID of the SocialAccount to target. Must be in the key's allowlist.",
    )
    caption: str = Field(..., max_length=10_000)
    title: str = Field(
        "",
        max_length=255,
        description="Required on platforms where ``needs_title=true`` (YouTube, Pinterest). Ignored otherwise.",
    )
    first_comment: str = Field(
        "",
        max_length=10_000,
        description=(
            "Auto-posted as a reply ~120s after the main post lands. "
            "Silently dropped at publish time when the target account's "
            "``supports_first_comment`` is false (TikTok, Pinterest, "
            "Bluesky, Google Business; LinkedIn Personal in OIDC mode)."
        ),
    )
    media_asset_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="MediaAsset IDs already uploaded to the workspace's media library. Position-ordered.",
    )
    platform_overrides: list[PlatformOverride] = Field(
        default_factory=list,
        description=(
            "Optional per-platform overrides of title / caption / first_comment. "
            "Each entry's social_account_id must equal the post's social_account_id "
            "in the current single-account API. Sending a field as ``null`` (or "
            "omitting it) leaves the post's default in place for that platform."
        ),
    )
    action: PostAction = Field(
        "draft",
        description=(
            "``draft`` parks the post for later editing/scheduling; "
            "``schedule`` requires ``scheduled_at`` and queues for publishing."
        ),
    )
    scheduled_at: dt.datetime | None = Field(
        None,
        description="UTC timestamp. Required when ``action='schedule'``.",
    )
    gate_id: uuid.UUID | None = Field(
        None,
        description=(
            "Approval-gate decision ID from agent-service. Required when "
            "``action='schedule'`` — a post cannot be queued for publishing "
            "without a passing gate. Optional for drafts."
        ),
    )
    idempotency_key: str | None = Field(
        None,
        max_length=128,
        description="Optional client-chosen retry key. Same key + same body → replay first response.",
    )


class UpdatePostRequest(Schema):
    caption: str | None = Field(None, max_length=10_000)
    title: str | None = Field(None, max_length=255)
    first_comment: str | None = Field(None, max_length=10_000)
    media_asset_ids: list[uuid.UUID] | None = None
    scheduled_at: dt.datetime | None = Field(
        None,
        description="If the post is currently scheduled, this re-times it. Ignored for drafts.",
    )


class ScheduleRequest(Schema):
    scheduled_at: dt.datetime = Field(..., description="UTC timestamp at which the publisher should fire the post.")


# ---------------------------------------------------------------------------
# /posts — read
# ---------------------------------------------------------------------------


class PlatformPostSummary(Schema):
    id: uuid.UUID
    social_account_id: uuid.UUID
    platform: str
    status: str
    scheduled_at: dt.datetime | None
    published_at: dt.datetime | None
    platform_post_id: str = ""

    @field_serializer("scheduled_at", "published_at")
    def _serialize_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)

    @classmethod
    def from_platform_post(cls, pp: PlatformPost) -> PlatformPostSummary:
        return cls(
            id=pp.id,
            social_account_id=pp.social_account_id,
            platform=pp.social_account.platform,
            status=pp.status,
            scheduled_at=pp.scheduled_at,
            published_at=pp.published_at,
            platform_post_id=pp.platform_post_id or "",
        )


class PostResponse(Schema):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    caption: str
    first_comment: str
    scheduled_at: dt.datetime | None
    published_at: dt.datetime | None
    status: str  # derived aggregate
    platform_posts: list[PlatformPostSummary]
    created_at: dt.datetime
    updated_at: dt.datetime

    @field_serializer("scheduled_at", "published_at", "created_at", "updated_at")
    def _serialize_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)

    @classmethod
    def from_post(cls, post: Post) -> PostResponse:
        """Single source of truth for Post → API response shape.

        Used by both the REST router and MCP handlers so the two surfaces
        cannot drift. ``post.platform_posts`` should be prefetched with
        ``social_account`` to avoid an N+1.
        """
        platform_posts = [
            PlatformPostSummary.from_platform_post(pp) for pp in post.platform_posts.select_related("social_account")
        ]
        return cls(
            id=post.id,
            workspace_id=post.workspace_id,
            title=post.title,
            caption=post.caption,
            first_comment=post.first_comment,
            scheduled_at=post.scheduled_at,
            published_at=post.published_at,
            status=post.status,
            platform_posts=platform_posts,
            created_at=post.created_at,
            updated_at=post.updated_at,
        )


# ---------------------------------------------------------------------------
# /media — write + read
# ---------------------------------------------------------------------------


class MediaAssetResponse(Schema):
    """Single MediaAsset as exposed to the API.

    ``url`` is whatever ``MediaAsset.file.url`` resolves to — a presigned
    URL with a configurable TTL on S3/R2, or a local ``/media/...`` path
    on local storage. Agents should treat it as short-lived and always
    reference the asset by ``id`` in subsequent calls.

    ``last_used_at`` is the max ``created_at`` across every Post that
    references this asset via ``PostMedia``. It is populated only on
    list/detail responses, never on the upload 201.
    """

    id: uuid.UUID
    # ``organization`` is a nullable FK on ``MediaAsset`` (see
    # [apps/media_library/models.py:93-99]). Pre-migration legacy rows can
    # exist with org=NULL, and Pydantic rejects them at response time if
    # this isn't optional. Staging hit this on 2026-06-01 with the agent
    # API media list endpoint.
    organization_id: uuid.UUID | None
    workspace_id: uuid.UUID | None
    filename: str
    media_type: str
    mime_type: str
    file_size: int
    file_size_display: str
    width: int
    height: int
    aspect_ratio: float
    duration: float
    title: str
    alt_text: str
    tags: list[str]
    folder_id: uuid.UUID | None
    is_starred: bool
    is_shared: bool
    processing_status: str
    url: str
    thumbnail_url: str | None
    last_used_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime

    @field_serializer("last_used_at", "created_at", "updated_at")
    def _serialize_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)

    @classmethod
    def from_asset(cls, asset, *, last_used_at: dt.datetime | None = None) -> MediaAssetResponse:
        return cls(
            id=asset.id,
            organization_id=asset.organization_id,
            workspace_id=asset.workspace_id,
            filename=asset.filename,
            media_type=asset.media_type,
            mime_type=asset.mime_type or "",
            file_size=int(asset.file_size or 0),
            file_size_display=asset.file_size_display,
            width=int(asset.width or 0),
            height=int(asset.height or 0),
            aspect_ratio=float(asset.aspect_ratio or 0),
            duration=float(asset.duration or 0),
            title=asset.title or "",
            alt_text=asset.alt_text or "",
            tags=list(asset.tags or []),
            folder_id=asset.folder_id,
            is_starred=bool(asset.is_starred),
            is_shared=bool(asset.is_shared),
            processing_status=asset.processing_status,
            url=_safe_file_url(asset.file),
            thumbnail_url=_safe_file_url(asset.thumbnail) or None,
            last_used_at=last_used_at,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
        )


def _safe_file_url(file_field) -> str:
    """Return ``file_field.url`` if the field is set, else ``""``.

    ``FileField.url`` raises ``ValueError`` when the field is blank, which
    happens for ``thumbnail`` on every asset before async processing
    finishes.
    """
    if not file_field:
        return ""
    try:
        return file_field.url or ""
    except (ValueError, AttributeError):
        return ""


class MediaAssetListResponse(Schema):
    items: list[MediaAssetResponse]
    next_cursor: str | None = None
    limit: int


# ---------------------------------------------------------------------------
# /analytics — read
# ---------------------------------------------------------------------------


class DerivedMetricResponse(Schema):
    """A single derived metric over a rolling window.

    Mirrors ``apps.analytics.derive.DerivedMetric`` but with a stable wire
    shape: agents can rely on every metric carrying the same five fields.
    The dataclass itself isn't a Pydantic model, so we route through
    :meth:`from_derived` rather than letting Ninja convert it implicitly.
    """

    key: str = Field(..., description="Metric identifier (e.g. ``views``, ``likes``, ``engagement``).")
    label: str = Field(..., description="Human-readable label for the metric (e.g. ``Views``).")
    kind: str = Field(..., description="Format hint: ``count`` | ``percent`` | ``minutes``.")
    value: float = Field(
        ...,
        description=(
            "Aggregate value over the current window. Sum for ``count`` metrics, "
            "average for ``percent`` and ``minutes`` (since those are already daily rates)."
        ),
    )
    delta: float = Field(
        ...,
        description="Percent change vs. the previous equal-length window. ``0.0`` when there is no prior baseline.",
    )
    series: list[float] = Field(
        default_factory=list,
        description="Daily values for the current window, oldest first.",
    )

    @classmethod
    def from_derived(cls, key: str, label: str, derived: DerivedMetric) -> DerivedMetricResponse:
        return cls(
            key=key,
            label=label,
            kind=derived.kind,
            value=derived.value,
            delta=derived.delta,
            series=list(derived.series),
        )


class EngagementCardResponse(Schema):
    rate: DerivedMetricResponse = Field(
        ...,
        description="Engagement rate = sum(parts) / denom * 100. The denom is the first available of ``reach, impressions, views, plays``.",
    )
    parts: list[DerivedMetricResponse] = Field(
        default_factory=list,
        description="The component metrics that feed the rate's numerator (likes, comments, shares, …).",
    )


class AccountAnalyticsResponse(Schema):
    """Channel-level analytics summary over a rolling window of days."""

    account_id: uuid.UUID
    platform: str
    account_name: str
    connection_status: str = Field(
        ...,
        description=(
            "``connected``, ``token_expiring``, ``disconnected``, or ``error``. "
            "Disconnected accounts still return historical analytics, but new data may not be flowing."
        ),
    )
    days: int = Field(..., description="Window size (in days) used for derivation. One of 7, 30, or 90.")
    analytics_available: bool = Field(
        ...,
        description=(
            "``false`` for platforms whose APIs don't expose aggregate analytics "
            "(currently LinkedIn Personal, Bluesky, Mastodon). Metric arrays are empty when false."
        ),
    )
    unavailable_reason: str | None = Field(
        None,
        description="Human-readable reason the analytics surface is unavailable, when ``analytics_available`` is false.",
    )
    hero_metrics: list[DerivedMetricResponse] = Field(
        default_factory=list,
        description="Top-line per-channel KPIs (reach-like counts). Engagement parts are in ``engagement.parts``.",
    )
    engagement: EngagementCardResponse | None = Field(
        None,
        description="Engagement-rate card, or ``null`` when the platform lacks a reach-like denominator.",
    )
    follower_growth: DerivedMetricResponse | None = Field(
        None,
        description="New followers / subscribers gained over the window, when the platform reports it.",
    )
    captured_at: dt.datetime | None = Field(
        None,
        description="Most recent ``captured_at`` across the account's snapshots. ``null`` if no rows yet.",
    )
    next_sync_eta: dt.datetime | None = Field(
        None,
        description=(
            "Approximate next time the background sync will refresh this account. "
            "``null`` for platforms without analytics. Use it to pick a polling delay."
        ),
    )

    @field_serializer("captured_at", "next_sync_eta")
    def _serialize_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)


class PostMetricTileResponse(Schema):
    """One metric tile in the per-post analytics drawer."""

    key: str
    label: str
    kind: str
    value: float = Field(..., description="Most recent snapshot value for this metric on this post.")
    series: list[float] = Field(
        default_factory=list,
        description="Daily sparkline since publish — one entry per day with a recorded snapshot.",
    )
    is_primary: bool = Field(
        False,
        description="True for the platform's default headline metric (e.g. ``views`` for YouTube).",
    )


class PlatformPostAnalyticsResponse(Schema):
    """Analytics for a single per-platform child of a Post."""

    platform_post_id: uuid.UUID
    social_account_id: uuid.UUID
    platform: str
    status: str
    published_at: dt.datetime | None
    analytics_available: bool = Field(
        ...,
        description=(
            "``false`` for platforms without analytics. ``true`` for everything else — including "
            "drafts and scheduled posts, which simply return empty metric tiles until publish."
        ),
    )
    unavailable_reason: str | None = None
    metric_tiles: list[PostMetricTileResponse] = Field(
        default_factory=list,
        description="One tile per metric this platform reports. Empty until the first snapshot lands.",
    )
    captured_at: dt.datetime | None = Field(
        None,
        description="Most recent ``captured_at`` across this platform-post's snapshots.",
    )
    next_sync_eta: dt.datetime | None = Field(
        None,
        description=(
            "Approximate next sync time based on the post's age: <24h→+1h, 1-7d→+6h, 7-30d→+1d, "
            "30-90d→+7d, >90d→null (syncs have stopped)."
        ),
    )

    @field_serializer("published_at", "captured_at", "next_sync_eta")
    def _serialize_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)


class PostAnalyticsResponse(Schema):
    """Analytics for a Post, with per-platform breakdown.

    Mirrors ``PostResponse``'s parent-Post-with-platform-children shape so
    agents that already track ``post_id`` from ``schedule_post`` /
    ``create_draft`` can poll analytics without learning new IDs.
    """

    post_id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    caption: str
    platform_posts: list[PlatformPostAnalyticsResponse]


# ---------------------------------------------------------------------------
# Error envelope (used by the exception handler in api.py)
# ---------------------------------------------------------------------------


class ErrorResponse(Schema):
    error: str
    detail: str | None = None
    tier: str | None = None
    limit: int | None = None
    remaining: int | None = None
    retry_after: int | None = None
    reset_at: dt.datetime | None = None


# ---------------------------------------------------------------------------
# /pipeline, /content, /campaigns, /overview — reporting surface
# ---------------------------------------------------------------------------


class PipelineStage(Schema):
    key: str = Field(..., description="Funnel stage key: curated|drafting|review|approved|scheduled|published.")
    label: str = Field(..., description="Human label for the stage.")
    count: int = Field(..., description="Number of content items currently in this stage.")
    pct: int = Field(..., description="This stage's count as a percent of the pipeline total (0-100).")
    color: str = Field(..., description="Hex colour for the stage bar.")


class PipelineResponse(Schema):
    stages: list[PipelineStage] = Field(..., description="Funnel stages in flow order.")
    total: int = Field(..., description="Total active content items (created + curated, de-duped).")
    created: int = Field(..., description="Composer posts with no linked intake item.")
    curated: int = Field(..., description="Intake-register rows (each counted once).")
    published: int = Field(..., description="Items in the published stage.")
    percent: int = Field(..., description="Weighted progress through the pipeline (0-100).")


class ContentPlatform(Schema):
    platform: str = Field(..., description="Platform key (e.g. linkedin, instagram, x).")
    account_id: uuid.UUID = Field(..., description="Target SocialAccount id.")
    status: str = Field(..., description="Per-platform editorial/publish status.")
    scheduled_at: dt.datetime | None = Field(None, description="When this child is scheduled.")
    published_at: dt.datetime | None = Field(None, description="When this child was published.")
    platform_post_id: str = Field("", description="Native post id on the platform once published.")
    error: str = Field("", description="Publish error, if the last attempt failed.")

    @field_serializer("scheduled_at", "published_at")
    def _ser_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)


class ContentItem(Schema):
    id: uuid.UUID = Field(..., description="Post id.")
    title: str = Field(..., description="Post title.")
    caption_preview: str = Field(..., description="First ~160 chars of the caption.")
    source: str = Field(..., description="created (composer-authored) | curated (from the intake register).")
    status: str = Field(..., description="Derived aggregate status across the post's platform children.")
    campaign: str = Field("", description="Free-form campaign label.")
    track: str = Field("", description="Programme track.")
    pillar: str = Field("", description="Sector pillar.")
    platforms: list[ContentPlatform] = Field(..., description="Per-platform children.")
    scheduled_at: dt.datetime | None = Field(None, description="Post-level scheduled time.")
    published_at: dt.datetime | None = Field(None, description="Post-level published time.")
    created_at: dt.datetime = Field(..., description="Creation time.")
    updated_at: dt.datetime = Field(..., description="Last update time.")

    @field_serializer("scheduled_at", "published_at", "created_at", "updated_at")
    def _ser_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)


class ContentListResponse(Schema):
    items: list[ContentItem] = Field(..., description="Page of content items.")
    next_cursor: str | None = Field(None, description="Opaque cursor for the next page; null at the end.")
    has_more: bool = Field(..., description="True if another page exists.")


class PlatformMetric(Schema):
    platform: str = Field(..., description="Platform key.")
    metrics: dict[str, float] = Field(..., description="Metric key → summed value for the platform.")


class AnalyticsRollup(Schema):
    available: bool = Field(..., description="False when the key lacks view_analytics or no account has analytics.")
    window_days: int = Field(..., description="Rolling window size in days.")
    accounts: int = Field(..., description="Number of allowlisted accounts contributing analytics.")
    totals: dict[str, float] = Field(..., description="Metric key → summed value across all platforms.")
    by_platform: list[PlatformMetric] = Field(..., description="Per-platform metric breakdown.")


class CampaignSummary(Schema):
    name: str = Field(..., description="Campaign label (the free-form Post.campaign string).")
    content_count: int = Field(..., description="Posts tagged with this campaign (allowlist-scoped).")
    by_status: dict[str, int] = Field(..., description="Derived-status → count.")
    platforms: list[str] = Field(..., description="Distinct platforms this campaign posts to.")
    first_post: dt.datetime | None = Field(None, description="Earliest post creation time in the campaign.")
    last_post: dt.datetime | None = Field(None, description="Latest post creation time in the campaign.")
    analytics: AnalyticsRollup | None = Field(
        None, description="Summed analytics over the campaign's accounts; null without view_analytics."
    )

    @field_serializer("first_post", "last_post")
    def _ser_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)


class CampaignListResponse(Schema):
    items: list[CampaignSummary] = Field(..., description="Campaign rollups, most-recent activity first.")


class ContentSummary(Schema):
    total: int = Field(..., description="Total allowlist-visible posts in the workspace.")
    by_status: dict[str, int] = Field(..., description="Derived-status → count.")
    scheduled_next_7d: int = Field(..., description="Posts scheduled in the next 7 days.")
    published_last_30d: int = Field(..., description="Posts published in the last 30 days.")


class OverviewResponse(Schema):
    workspace_id: uuid.UUID = Field(..., description="The workspace this rollup covers.")
    generated_at: dt.datetime = Field(..., description="When the rollup was computed (UTC).")
    pipeline: PipelineResponse = Field(..., description="Content pipeline funnel.")
    content: ContentSummary = Field(..., description="Content counts + scheduling windows.")
    campaigns: list[CampaignSummary] = Field(..., description="Top campaigns by recent activity.")
    analytics: AnalyticsRollup = Field(..., description="Workspace analytics rollup (gated).")

    @field_serializer("generated_at")
    def _ser_dt(self, value: dt.datetime) -> str | None:
        return _serialize_utc_z(value)
