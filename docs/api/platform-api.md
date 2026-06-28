# Campaign OS — Platform API Reference

The complete external API for the Campaign OS platform: identity, connected
channels, media, the post compose→schedule→publish lifecycle, analytics,
workspace reporting rollups, and the MCP transport. One bearer token, one base
URL, one set of conventions.

This is the full reference. For a focused walkthrough of just the read-only
reporting/aggregation endpoints, see [`reporting-api.md`](./reporting-api.md).

- **Base URL (production):** `https://web-production-2f84d.up.railway.app`
- **API root:** `https://web-production-2f84d.up.railway.app/api/v1`
- **Interactive docs (Swagger, always current):** `…/api/v1/docs`
- **OpenAPI JSON:** `…/api/v1/openapi.json`
- **Title / version:** `Campaign OS Agent API` `1.0.0`

> If a custom domain (e.g. `api.africacen.org`) is mapped later, swap the host —
> the paths are identical.

---

## 1. Endpoint map

| Area | Method & path | Permission | Purpose |
|---|---|---|---|
| Identity | `GET /api/v1/me` | any key | Inspect this key's scope (workspace, permissions, accounts, storage) |
| Channels | `GET /api/v1/accounts` | any key | List the social accounts this key may act on |
| Media | `POST /api/v1/media` | `upload_media` | Upload a media asset (multipart) |
| Media | `GET /api/v1/media` | any key | List/search media assets (paginated) |
| Media | `GET /api/v1/media/{media_id}` | any key | Retrieve one media asset |
| Posts | `POST /api/v1/posts` | `create_posts` | Create a draft or scheduled post |
| Posts | `GET /api/v1/posts/{post_id}` | any key | Read a single post |
| Posts | `PATCH /api/v1/posts/{post_id}` | `create_posts` | Update draft fields |
| Posts | `POST /api/v1/posts/{post_id}/schedule` | `create_posts` | Schedule a draft |
| Posts | `POST /api/v1/posts/{post_id}/cancel` | `create_posts` | Cancel a scheduled post (→ draft) |
| Analytics | `GET /api/v1/analytics/accounts/{account_id}` | `view_analytics` | Channel analytics summary |
| Analytics | `GET /api/v1/analytics/posts/{post_id}` | `view_analytics` | Per-platform post analytics |
| Reporting | `GET /api/v1/overview` | any key¹ | One-call workspace dashboard rollup |
| Reporting | `GET /api/v1/content` | any key | List everything being posted (filterable) |
| Reporting | `GET /api/v1/campaigns` | any key¹ | Campaign rollups |
| Reporting | `GET /api/v1/pipeline` | any key | Content pipeline funnel |
| MCP | `POST /api/v1/mcp` | any key | MCP Streamable HTTP (JSON-RPC) — same tools, MCP wire format |

¹ Counts return for any key; the embedded **analytics numbers** require
`view_analytics` (otherwise `analytics.available: false`).

---

## 2. Authentication

Every request requires a bearer token. There is no anonymous surface.

### Create a key
**Organization → API Keys** (`/organizations/api-keys/`) → **Issue new key**.
Choose: a **workspace**, the **social accounts** the key may touch (its
allowlist), and the **permissions** to grant. Copy the `cos_…` token shown
once — it is never displayed again. (Issuer must be an org owner/admin.)

### Use it
```
Authorization: Bearer cos_your_token_here
```

- **HTTPS only** — plaintext requests are rejected (`401`) in production.
- Missing/invalid/expired/revoked token → `401`.

---

## 3. Conventions

- **Datetimes** — ISO-8601 UTC with a trailing `Z` (e.g. `2026-06-28T08:00:00Z`).
  Send timestamps the same way.
- **IDs** — UUID strings.
- **Scope** — every response is bounded by the key's **workspace** and its
  **account allowlist**. A key never sees another workspace's data, nor posts/
  analytics for accounts it isn't allowlisted on.
- **Pagination** — list endpoints (`/content`, `/media`) use an opaque cursor:
  pass the prior response's `next_cursor` as `?cursor=`; stop when
  `has_more` is `false`.
- **Idempotency** — `POST /posts` accepts an `idempotency_key` (in the body or
  the `Idempotency-Key` header): the same key + same body replays the first
  response instead of creating a duplicate.

---

## 4. Rate limits

| Tier | Limit |
|---|---|
| Per-key reads | 300 / minute |
| Per-key writes | 120 / minute |
| Per-workspace aggregate | 1000 / minute |
| Per-account publishing | 24h rolling cap per platform (e.g. Instagram 25/day, LinkedIn 100/day) |

Over-limit → `429` with a `Retry-After` header and body:
```jsonc
{ "error": "rate_limited", "tier": "per_key_reads", "limit": 300, "remaining": 0, "retry_after": 12 }
```
`X-RateLimit-Limit` / `X-RateLimit-Remaining` are emitted **only on 429s**.

---

## 5. Error envelope

All errors share one shape:
```jsonc
{ "error": "forbidden", "detail": "Permission denied: view_analytics" }
```

| Status | Meaning |
|---|---|
| `400` | Bad request |
| `401` | Missing/invalid token, or `http://` used |
| `403` | Key lacks the required permission, or targets a non-allowlisted account |
| `404` | Not found (also returned for foreign/out-of-scope IDs — no existence leak) |
| `413` | Upload exceeds the workspace storage quota |
| `422` | Validation error (bad param/body) |
| `429` | Rate limited |

---

## 6. Identity & channels

### `GET /api/v1/me`
Inspect what this key can do. Call it first.
```bash
curl -s -H "Authorization: Bearer $TOKEN" "$API/me" | jq
```
```jsonc
{
  "api_key_id": "…", "workspace_id": "…", "workspace_name": "WAIIS",
  "organization_id": "…",
  "permissions": ["create_posts", "view_analytics", "upload_media", …],
  "storage": { "used_bytes": 1234567, "limit_bytes": 5368709120, "remaining_bytes": … },
  "allowlisted_accounts": [ { "id": "…", "platform": "linkedin", "account_name": "AfCEN", … } ]
}
```

### `GET /api/v1/accounts`
The social accounts this key may target, with per-platform capabilities.
```jsonc
{
  "accounts": [
    {
      "id": "5b2e…", "platform": "linkedin", "account_name": "AfCEN",
      "account_handle": "afcen", "connection_status": "connected",
      "char_limit": 3000, "needs_title": false, "supports_first_comment": true
    }
  ]
}
```
Use `char_limit` / `needs_title` / `supports_first_comment` to validate locally
**before** composing (e.g. drop `first_comment` for TikTok/Bluesky).

---

## 7. Media

### `POST /api/v1/media` — upload (multipart/form-data)
Requires `upload_media`. Upload assets before referencing them by ID in a post.
```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -F "file=@./hero.jpg" -F "title=EGM hero" -F "alt_text=Conference hall" -F "tags=egm,energy" \
  "$API/media"
```
Returns a `MediaAssetResponse` (see below). `413` if it would exceed the
workspace storage quota.

### `GET /api/v1/media` — list / search (paginated)
Query params: `q` (filename+tags substring), `media_type` (`image|video|gif|document`),
`tags` (CSV, all must match), `folder_id`, `is_starred`, `processing_status`
(default `completed`, or `any`), `created_after`, `created_before`, `order_by`
(default `-created_at`), `cursor`, `limit` (1–100, default 20).
```jsonc
{ "items": [ MediaAssetResponse, … ], "next_cursor": "…|null", "limit": 20 }
```

### `GET /api/v1/media/{media_id}`
One asset.

**`MediaAssetResponse`** fields: `id`, `organization_id`, `workspace_id`,
`filename`, `media_type`, `mime_type`, `file_size`, `file_size_display`,
`width`, `height`, `aspect_ratio`, `duration`, `title`, `alt_text`, `tags`,
`folder_id`, `is_starred`, `is_shared`, `processing_status`, `url`,
`thumbnail_url`, `last_used_at`, `created_at`, `updated_at`.

---

## 8. Posts — compose → schedule → publish

A **Post** is the publishable unit; it has one or more **platform children**
(one per target account). `Post.status` is derived from its children:
`draft → pending_review → approved → scheduled → publishing → published`
(or `failed` / `partially_published`).

### `POST /api/v1/posts` — create a draft or scheduled post
Requires `create_posts`. Body (`CreatePostRequest`):

| Field | Type | Notes |
|---|---|---|
| `social_account_id` | string *req | Target account; must be in the key's allowlist |
| `caption` | string *req | The post body |
| `title` | string | Required where `needs_title=true` (YouTube, Pinterest) |
| `first_comment` | string | Auto-posted ~120s after publish; dropped where unsupported |
| `media_asset_ids` | array | MediaAsset IDs (position-ordered) |
| `platform_overrides` | array | Per-platform title/caption/first_comment overrides |
| `action` | string | `draft` (default) or `schedule` |
| `scheduled_at` | string | UTC; **required when `action=schedule`** |
| `gate_id` | string | Approval-gate decision ID; **required when `action=schedule`** |
| `idempotency_key` | string | Same key + body → replays the first response |

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"social_account_id":"5b2e…","caption":"African energy leaders convene at the EGM.","action":"draft"}' \
  "$API/posts"
```
Returns `201` (created) with a `PostResponse`.

> **The publish gate.** Going live always passes through the approval gate at the
> publish chokepoint. To schedule, supply a `gate_id` from the approval flow;
> publishing a post whose content changed re-gates it.

### `GET /api/v1/posts/{post_id}` — read one post
Returns `PostResponse`:
```jsonc
{
  "id": "9a1c…", "workspace_id": "…", "title": "…", "caption": "…",
  "first_comment": "…", "scheduled_at": "…|null", "published_at": "…|null",
  "status": "scheduled",
  "platform_posts": [
    { "id":"…","social_account_id":"…","platform":"linkedin","status":"scheduled",
      "scheduled_at":"…","published_at":null,"platform_post_id":"" }
  ],
  "created_at": "…", "updated_at": "…"
}
```

### `PATCH /api/v1/posts/{post_id}` — update draft fields
Requires `create_posts`. Body (`UpdatePostRequest`, all optional): `caption`,
`title`, `first_comment`, `media_asset_ids`, `scheduled_at` (re-times a
scheduled post; ignored for drafts). Editing caption/first_comment clears the
gate decision — it must be re-approved before it can publish.

### `POST /api/v1/posts/{post_id}/schedule` — schedule a draft
Requires `create_posts`. Body (`ScheduleRequest`): `scheduled_at` (UTC) *req.

### `POST /api/v1/posts/{post_id}/cancel` — cancel a scheduled post
Requires `create_posts`. Moves it back to `draft`. (Posts cannot be deleted via
the API; published posts remain as audit records.)

---

## 9. Analytics

Both require `view_analytics` and respect the account allowlist.

### `GET /api/v1/analytics/accounts/{account_id}`
Channel summary over a rolling window. Query: `days` (7–90, default 30).
```jsonc
{
  "account_id":"…","platform":"instagram","account_name":"…","connection_status":"connected",
  "days":30,"analytics_available":true,
  "hero_metrics":[ {"key":"reach","label":"Reach","kind":"count","value":12000,"delta":8.5,"series":[…]} ],
  "engagement":{ … }, "follower_growth":{ … },
  "captured_at":"…","next_sync_eta":"…"
}
```
Platforms without a live analytics surface (e.g. LinkedIn Personal, Bluesky,
Mastodon) return `analytics_available:false` with empty arrays.

### `GET /api/v1/analytics/posts/{post_id}`
Per-platform-child metrics for one post (each child reports availability
independently). Drafts/scheduled children return empty metric tiles, not an
error.

---

## 10. Reporting (workspace rollups)

Read-only aggregation across the whole workspace. Full guide:
[`reporting-api.md`](./reporting-api.md). Counts return for any valid key;
embedded analytics numbers require `view_analytics`.

- **`GET /api/v1/overview?days=30`** — pipeline funnel + content counts + top-10
  campaigns + analytics totals in one call.
- **`GET /api/v1/content`** — paginated list of all posts. Filters: `status`,
  `campaign`, `platform`, `source` (`created|curated`), `scheduled_after`,
  `scheduled_before`, `cursor`, `limit` (1–100). Returns
  `{ items, next_cursor, has_more }`.
- **`GET /api/v1/campaigns?days=30`** — per-campaign rollups (counts by status,
  platforms, date range, analytics).
- **`GET /api/v1/pipeline`** — the funnel only: `{ stages[], total, created,
  curated, published, percent }`.

---

## 11. MCP transport

### `POST /api/v1/mcp`
The same capabilities as the REST surface, exposed over the **Model Context
Protocol** (Streamable HTTP, JSON-RPC over POST). Same bearer auth, same audit
log, same rate limits, same per-account scoping — only the wire format differs.
Point an MCP-compatible client (agent runtime) at this URL with the
`Authorization: Bearer cos_…` header.

---

## 12. Permission keys

Granted per key at issuance. Reference:

`create_posts`, `edit_others_posts`, `approve_posts`, `publish_directly`,
`manage_social_accounts`, `view_analytics`, `use_inbox`, `reply_from_inbox`,
`manage_workspace_settings`, `upload_media`, `edit_media`, `delete_media`,
`manage_media`.

For a **read-only reporting/dashboard key**: grant `view_analytics` and
allowlist all the workspace's accounts. For an **agent that composes & schedules
content**: grant `create_posts` + `upload_media` (+ `view_analytics` to observe
performance).

---

## 13. A typical agent flow

```text
1. GET  /me                      → confirm workspace, permissions, accounts
2. GET  /accounts                → pick a target account, read its char_limit/capabilities
3. POST /media                   → upload image(s), keep the returned IDs
4. POST /posts {action:"draft"}  → create the draft (caption + media_asset_ids)
   … content is reviewed/approved through the gate, yielding a gate_id …
5. POST /posts/{id}/schedule     → schedule it (or POST /posts with action:"schedule"+gate_id)
6. GET  /analytics/posts/{id}    → after it publishes, poll performance
7. GET  /overview                → workspace-wide rollup for the dashboard
```

---

## 14. Reference

- **Live, always-current schema:** `…/api/v1/docs` (Swagger — try calls in-browser).
- **Reporting deep-dive:** [`reporting-api.md`](./reporting-api.md)
- **Implementation:** `apps/api/` (routers in `apps/api/routers/`, schemas in
  `apps/api/schemas.py`), `apps/api_keys/` (issuance), `apps/mcp/` (MCP transport).

```bash
# Handy shell setup
export TOKEN="cos_your_token_here"
export API="https://web-production-2f84d.up.railway.app/api/v1"
curl -s -H "Authorization: Bearer $TOKEN" "$API/me" | jq
```
