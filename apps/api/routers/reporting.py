"""``/api/v1/{overview,content,campaigns,pipeline}`` — read-only reporting.

Workspace-level rollups for dashboards and agents. Every route:

1. Enforces read-tier HTTP rate limits.
2. Scopes to the key's workspace and (for content) account allowlist.
3. Gates analytics *numbers* behind ``view_analytics`` — counts are open to
   any valid key, the same data class as reading a post.
4. Delegates assembly to per-app ``api_builders`` so MCP can reuse it.
5. Writes a ``reporting.*.read`` audit row on the way out.
"""
from __future__ import annotations

import base64
import json
import uuid

from django.http import HttpRequest
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError

from apps.analytics.api_builders import account_metric_map, build_workspace_analytics_rollup
from apps.api.limits import enforce_http_rate_limits
from apps.api.middleware import log_audit_entry
from apps.api.schemas import (
    CampaignListResponse,
    ContentListResponse,
    ContentSummary,
    OverviewResponse,
    PipelineResponse,
)
from apps.composer.api_builders import build_campaigns, build_content_list, build_content_summary
from apps.content_intake.progress import content_pipeline_progress

router = Router(tags=["reporting"])

_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100
_OVERVIEW_CAMPAIGN_LIMIT = 10


def _require_perm(request: HttpRequest, key: str) -> None:
    membership = getattr(request, "workspace_membership", None)
    if membership is None or not membership.effective_permissions.get(key, False):
        raise HttpError(403, f"Permission denied: {key}")


def _has_perm(request: HttpRequest, key: str) -> bool:
    membership = getattr(request, "workspace_membership", None)
    return bool(membership and membership.effective_permissions.get(key, False))


def _allowed_account_ids(request: HttpRequest) -> set[uuid.UUID]:
    return {sa.id for sa in request.api_key.social_accounts.all()}  # type: ignore[attr-defined]


def _allowlisted_accounts(request: HttpRequest):
    """The key's allowlisted SocialAccount rows (for analytics rollups)."""
    return list(request.api_key.social_accounts.all())  # type: ignore[attr-defined]


def _decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode() + b"==")
        return json.loads(raw.decode())
    except (ValueError, json.JSONDecodeError) as exc:
        raise HttpError(422, "Invalid cursor.") from exc


def _encode_cursor(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).rstrip(b"=").decode()


@router.get("/pipeline", response=PipelineResponse, summary="Content pipeline funnel for the workspace")
def pipeline(request):
    enforce_http_rate_limits(request, is_write=False)
    funnel = content_pipeline_progress(request.workspace)
    log_audit_entry(request, action="reporting.pipeline.read", target_id=None, status_code=200)
    return funnel


@router.get("/content", response=ContentListResponse, summary="List all content being posted")
def content(
    request,
    status: str | None = Query(None, description="Filter by derived post status (e.g. scheduled, published, failed)."),
    campaign: str | None = Query(None, description="Exact campaign-label match."),
    platform: str | None = Query(None, description="Only posts with a child on this platform."),
    source: str | None = Query(None, description="created | curated."),
    scheduled_after: str | None = Query(None, description="ISO datetime lower bound on scheduled_at."),
    scheduled_before: str | None = Query(None, description="ISO datetime upper bound on scheduled_at."),
    cursor: str | None = Query(None, description="Opaque pagination cursor from a prior response."),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Page size (1-100)."),
):
    enforce_http_rate_limits(request, is_write=False)
    offset = int(_decode_cursor(cursor).get("o", 0)) if cursor else 0
    items, has_more = build_content_list(
        request.workspace,
        _allowed_account_ids(request),
        status=status,
        campaign=campaign,
        platform=platform,
        source=source,
        scheduled_after=scheduled_after,
        scheduled_before=scheduled_before,
        limit=limit,
        offset=offset,
    )
    body = ContentListResponse(
        items=items,
        next_cursor=_encode_cursor({"o": offset + limit}) if has_more else None,
        has_more=has_more,
    )
    log_audit_entry(request, action="reporting.content.read", target_id=None, status_code=200)
    return body


@router.get("/campaigns", response=CampaignListResponse, summary="Campaign rollups (grouped by campaign label)")
def campaigns(
    request,
    days: int = Query(30, ge=7, le=90, description="Analytics rolling window in days."),
):
    enforce_http_rate_limits(request, is_write=False)
    amap = account_metric_map(_allowlisted_accounts(request), days) if _has_perm(request, "view_analytics") else None
    items = build_campaigns(
        request.workspace,
        _allowed_account_ids(request),
        days=days,
        account_map=amap,
    )
    log_audit_entry(request, action="reporting.campaigns.read", target_id=None, status_code=200)
    return CampaignListResponse(items=items)


@router.get("/overview", response=OverviewResponse, summary="One-call workspace dashboard rollup")
def overview(
    request,
    days: int = Query(30, ge=7, le=90, description="Analytics rolling window in days."),
):
    enforce_http_rate_limits(request, is_write=False)
    workspace = request.workspace
    allowed_ids = _allowed_account_ids(request)

    amap = account_metric_map(_allowlisted_accounts(request), days) if _has_perm(request, "view_analytics") else None

    summary = build_content_summary(workspace, allowed_ids)
    body = OverviewResponse(
        workspace_id=workspace.id,
        generated_at=timezone.now(),
        pipeline=content_pipeline_progress(workspace),
        content=ContentSummary(**summary),
        campaigns=build_campaigns(workspace, allowed_ids, days=days, account_map=amap, limit=_OVERVIEW_CAMPAIGN_LIMIT),
        analytics=build_workspace_analytics_rollup(amap if amap is not None else {}, days),
    )
    log_audit_entry(request, action="reporting.overview.read", target_id=None, status_code=200)
    return body
