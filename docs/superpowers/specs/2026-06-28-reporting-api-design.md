# Reporting / Aggregation API — Design

**Date:** 2026-06-28
**Status:** Approved (brainstorm), ready for implementation plan
**Surface:** `apps/api` (Django-Ninja Agent API, `/api/v1/`)

## Problem

There is no way to pull a workspace-level picture of *what content exists and how
it is performing* in one place. The Agent API today only reads a **single** post
(`GET /posts/{id}`) or a **single** account/post's analytics
(`GET /analytics/accounts/{id}`, `GET /analytics/posts/{id}`). A dashboard, an
n8n flow, or an agent that wants "content pipeline status, analytics, campaigns,
and everything being posted" has to know every UUID in advance — there is no list
or rollup surface.

## Goal

Add **read-only aggregation endpoints** to the existing `/api/v1/` Agent API that
expose:

1. A one-call **overview** rollup (pipeline funnel + content counts + campaign
   rollups + top-line analytics).
2. A paginated **content list** of everything being posted, with filters.
3. **Campaign** rollups (grouped by the existing free-form campaign string).
4. The **pipeline** funnel (curated → drafting → review → approved → scheduled →
   published).

## Non-Goals (YAGNI)

- **No formal `Campaign` model.** Campaign stays the free-form `Post.campaign`
  string; we aggregate by it. A real Campaign table would be its own spec.
- **No write paths.** Read-only.
- **No new permission.** Reuse the existing `view_analytics` for the analytics
  numbers; counts/listing reuse ordinary valid-key access (same class as reading a
  post).
- **No MCP wiring now.** Response assembly lives in reusable `api_builders` so the
  MCP transport *can* expose these later without divergence — but we do not add
  MCP tools in this change.
- **Curated-but-not-yet-drafted intake** (ContentIntake rows with no linked Post)
  appear only in the **pipeline funnel counts**, not the per-item content list.
  "Content being posted" = `Post`.

## Architecture

### Placement

A new router `apps/api/routers/reporting.py` holding all four GET routes, mounted
in `apps/api/api.py` at **root** so URLs read:

```
GET /api/v1/overview
GET /api/v1/content
GET /api/v1/campaigns
GET /api/v1/pipeline
```

Mounted after the existing routers and before `/mcp`, with distinct first path
segments (`overview`, `content`, `campaigns`, `pipeline`) so it cannot shadow
`/me`, `/accounts`, `/posts`, `/media`, `/analytics`.

### Every route

Mirrors the existing router contract, in this order:

1. `enforce_http_rate_limits(request, is_write=False)` (read tier).
2. Permission / scope checks (see **Access scoping**).
3. Build the response via an `api_builders` function (owning app).
4. `log_audit_entry(request, action="reporting.<name>.read", target_id=None, status_code=200)`.

### Response builders (the "byte-equal" convention)

| Builder | Module | Returns |
|---|---|---|
| `build_content_list(workspace, allowed_account_ids, *, filters, limit, cursor)` | `apps/composer/api_builders.py` | content page + next cursor |
| `build_campaigns(workspace, allowed_account_ids, *, days, include_analytics)` | `apps/composer/api_builders.py` | campaign rollups |
| `build_workspace_analytics_rollup(accounts, days)` | `apps/analytics/api_builders.py` | totals + per-platform |
| `content_pipeline_progress(workspace)` | `apps/content_intake/progress.py` (**existing, reused**) | funnel |
| overview composition | `apps/api/routers/reporting.py` route | composes the above |

## Endpoint contracts

### `GET /api/v1/overview` → `OverviewResponse`

```jsonc
{
  "workspace_id": "uuid",
  "generated_at": "2026-06-28T12:00:00Z",
  "pipeline": {
    "stages": [{ "key": "curated", "label": "Curated", "count": 12, "pct": 0.0, "color": "..." }, ...],
    "total": 80, "created": 30, "curated": 50, "published": 17, "percent": 0.42
  },
  "content": {
    "total": 80,
    "by_status": { "draft": 10, "pending_review": 4, "approved": 6, "scheduled": 5,
                   "publishing": 1, "published": 50, "failed": 4, ... },
    "scheduled_next_7d": 5,
    "published_last_30d": 22
  },
  "campaigns": [
    { "name": "EGM Launch", "content_count": 24, "by_status": {...},
      "platforms": ["linkedin","x"], "first_post": "...", "last_post": "...",
      "analytics": { "available": true, "impressions": 12000, "engagement": 430 } }
  ],
  "analytics": {
    "available": true, "window_days": 30, "accounts": 6,
    "totals": { "impressions": 50000, "engagement": 1800, "followers": 9000 },
    "by_platform": [ { "platform": "linkedin", "impressions": 30000, "engagement": 1200 }, ... ]
  }
}
```

- `campaigns` is the top **N=10** campaigns by most-recent activity.
- `analytics` block and per-campaign `analytics` are populated only when the key
  has `view_analytics`; otherwise `"available": false` and metric fields are
  `null` (mirrors `build_account_analytics`'s existing "not available" shape).

### `GET /api/v1/content` → `ContentListResponse`

```jsonc
{ "items": [ ContentItem ], "next_cursor": "opaque|null", "has_more": false }
```
`ContentItem`:
```jsonc
{ "id": "uuid", "title": "...", "caption_preview": "first ~160 chars",
  "source": "created" | "curated",
  "status": "scheduled", "campaign": "EGM Launch", "track": "...", "pillar": "...",
  "platforms": [ { "platform": "linkedin", "account_id": "uuid", "status": "scheduled",
                   "scheduled_at": "...", "published_at": null,
                   "platform_post_id": null, "error": null } ],
  "scheduled_at": "...", "published_at": null,
  "created_at": "...", "updated_at": "..." }
```

Query params (all optional):

| Param | Type | Notes |
|---|---|---|
| `status` | enum (derived Post status) | `draft,scheduled,publishing,published,failed,partially_published` |
| `campaign` | string | exact match on `Post.campaign` |
| `platform` | string | matches a platform child's account platform |
| `source` | `created` \| `curated` | by `intake_source` presence |
| `scheduled_after` / `scheduled_before` | ISO datetime | range on `scheduled_at` |
| `limit` | int 1..100 (default 25) | mirror `media` router caps |
| `cursor` | opaque | offset cursor, same encoding as `media` router |

Ordering: `-created_at, id` (stable for the offset cursor).

### `GET /api/v1/campaigns` → `CampaignListResponse`

```jsonc
{ "items": [ CampaignSummary ] }
```
`CampaignSummary` = same object as in `overview.campaigns`. Excludes blank
campaign strings. `?days=` (7..90, default 30) controls the analytics window;
`?include_analytics=` is implied by the key's `view_analytics` grant.

### `GET /api/v1/pipeline` → `PipelineResponse`

The funnel object from `content_pipeline_progress(workspace)`:
```jsonc
{ "stages": [ { "key","label","count","pct","color" } ],
  "total": 80, "created": 30, "curated": 50, "published": 17, "percent": 0.42 }
```

## Access scoping (security-critical)

- **Workspace wall.** Everything filtered to `request.api_key.workspace_id`. A key
  never sees another house's content (existing cross-house invariant).
- **Account allowlist** (`allowed_account_ids = {sa.id for sa in request.api_key.social_accounts.all()}`):
  - `GET /content`: a `Post` is included iff **(it has ≥1 platform child AND every
    child's `social_account_id ∈ allowed_account_ids)** OR (it has 0 platform
    children — a pure draft not yet targeting any account)**. This is exactly the
    rule `_get_workspace_post` enforces for single-post reads, so a partial-scope
    key cannot enumerate posts touching accounts it is not allowlisted on.
  - Analytics totals (`overview.analytics`, per-campaign `analytics`) are summed
    **only over accounts in `allowed_account_ids`**, consistent with
    `GET /analytics/accounts/{id}` requiring the account be in the allowlist.
- **Permission split.**
  - Content list, pipeline funnel, and campaign *counts*: any valid workspace key
    (same data class as reading a post). No `view_analytics` required.
  - Analytics *numbers* (overview `analytics` block + each campaign's `analytics`):
    require `view_analytics`. Absent it, those fields are `null` /
    `"available": false`; the rest of the payload still returns.
- **Pipeline funnel** is workspace-wide aggregate stage counts (reuses
  `content_pipeline_progress`); it returns counts only (no foreign captions or
  identities), so it is exposed to any valid workspace key.

## Schemas

Add to `apps/api/schemas.py`, following existing conventions (ISO-8601 `Z`
datetimes, UUID-as-string, a `description=` on every field for OpenAPI):

`OverviewResponse`, `PipelineStage`, `PipelineResponse`, `ContentPlatform`,
`ContentItem`, `ContentListResponse`, `CampaignSummary`, `CampaignListResponse`,
`AnalyticsRollup`.

## Error handling

Reuses the existing global handlers in `apps/api/api.py` (structured `{error,
detail}` envelope, 429 quota body, audit-on-failure). New failure audit labels:
`reporting.overview.read.<code>`, `reporting.content.read.<code>`,
`reporting.campaigns.read.<code>`, `reporting.pipeline.read.<code>` (extend
`_action_for_path`).

## Testing (TDD)

New `apps/api/tests/test_reporting_router.py`:

- **overview**: pipeline + content counts + campaign rollups + analytics present;
  `scheduled_next_7d` / `published_last_30d` windows correct.
- **content list**: each filter (`status`, `campaign`, `platform`, `source`,
  date range); cursor pagination (`limit`, `next_cursor`, `has_more`); ordering
  stable.
- **scoping**: partial-scope key cannot see a post whose child targets a
  non-allowlisted account; cross-house key sees nothing of the other house;
  analytics totals exclude non-allowlisted accounts.
- **permission**: key without `view_analytics` gets counts but
  `analytics.available == false` and null metrics; key with it gets numbers.
- **plumbing**: a `reporting.*.read` audit row is written; read rate-limit is
  enforced (429 shape).
- **pipeline**: response equals `content_pipeline_progress(workspace)`.

Builder unit tests live in the owning apps
(`apps/composer/tests/`, `apps/analytics/tests/`).

Run: `uv run pytest -x -q apps/api/tests/test_reporting_router.py` then the full
suite.

## Open questions resolved

- Campaigns: **aggregate-by-string** (no model).
- URLs: **root-level** (`/api/v1/overview`, …).
- Permission: **split** (counts open to any valid key; analytics numbers gated on
  `view_analytics`).
