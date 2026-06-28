# Reporting API — Connection Guide

How to connect to and consume the **Campaign OS Reporting API**: read-only,
workspace-wide endpoints for content pipeline status, everything being posted,
campaign rollups, and top-line analytics.

These routes live on the existing **Agent API** at `/api/v1/`, so they share its
authentication, rate limits, and OpenAPI docs.

- **Base URL (production):** `https://web-production-2f84d.up.railway.app`
- **Interactive docs (Swagger):** `https://web-production-2f84d.up.railway.app/api/v1/docs`
- **OpenAPI JSON:** `https://web-production-2f84d.up.railway.app/api/v1/openapi.json`

> The base URL above is the current Railway production host. If a custom domain
> (e.g. `api.africacen.org`) is mapped later, swap it in — the paths are
> identical. To confirm any host, open `/api/v1/docs` in a browser; if it loads,
> that's a valid base host.

---

## 1. Endpoints at a glance

| Method & path | What it returns |
|---|---|
| `GET /api/v1/overview` | One-call dashboard rollup: pipeline funnel + content counts + top campaigns + analytics totals |
| `GET /api/v1/content` | Paginated list of **all content being posted** (filterable) |
| `GET /api/v1/campaigns` | Per-campaign rollups (grouped by the campaign label) |
| `GET /api/v1/pipeline` | The content pipeline funnel (curated → … → published) |

All four are **read-only** (`GET`) and scoped to the workspace your API key
belongs to.

---

## 2. Authentication

Every request needs a **bearer token** (an API key). There is no anonymous
access — a key is required even to read the pipeline.

### 2.1 Create an API key

1. In Campaign OS, go to **Organization → API Keys**
   (`https://web-production-2f84d.up.railway.app/organizations/api-keys/`).
2. Click **Issue key** and choose:
   - **Workspace** — the house the key reads from (e.g. WAIIS, AfCEN). A key
     sees only this workspace's content.
   - **Social accounts (allowlist)** — the channels the key may see. For a
     reporting/dashboard key, select **all** the workspace's accounts so it can
     see every post and all analytics. (See §6 for what a partial allowlist
     hides.)
   - **Permissions** — include **`view_analytics`** if you want analytics
     numbers in the responses. Without it, you still get all the counts, but the
     `analytics` blocks come back empty (`available: false`). See §6.
3. Copy the token shown **once** (it starts with `cos_…`). Store it as a secret —
   it is never displayed again.

### 2.2 Send the token

Add it as an `Authorization: Bearer` header on every request:

```
Authorization: Bearer cos_your_token_here
```

### 2.3 Requirements

- **HTTPS only.** Plaintext (`http://`) requests are rejected in production with
  a `401`. Always call the `https://` host.
- A missing, malformed, revoked, or expired token returns `401`.

---

## 3. Quick start

```bash
TOKEN="cos_your_token_here"
HOST="https://web-production-2f84d.up.railway.app"

# One-call dashboard rollup
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/overview" | jq
```

If you get a JSON object back with `pipeline`, `content`, `campaigns`, and
`analytics` keys, you're connected.

---

## 4. The endpoints in detail

### 4.1 `GET /api/v1/overview`

The single call most dashboards want. Optional query param:

- `days` (7–90, default `30`) — the analytics rolling window.

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/overview?days=30" | jq
```

```jsonc
{
  "workspace_id": "0c2f…",
  "generated_at": "2026-06-28T12:00:00Z",
  "pipeline": {
    "stages": [
      { "key": "curated",   "label": "Curated",   "count": 12, "pct": 15, "color": "#e7e5e4" },
      { "key": "drafting",  "label": "Drafting",  "count": 8,  "pct": 10, "color": "#fed7aa" },
      { "key": "review",    "label": "In review", "count": 4,  "pct": 5,  "color": "#fdba74" },
      { "key": "approved",  "label": "Approved",  "count": 6,  "pct": 8,  "color": "#fb923c" },
      { "key": "scheduled", "label": "Scheduled", "count": 5,  "pct": 6,  "color": "#f97316" },
      { "key": "published", "label": "Published", "count": 45, "pct": 56, "color": "#c2410c" }
    ],
    "total": 80, "created": 30, "curated": 50, "published": 45, "percent": 62
  },
  "content": {
    "total": 80,
    "by_status": { "draft": 10, "scheduled": 5, "publishing": 1, "published": 60, "failed": 4 },
    "scheduled_next_7d": 5,
    "published_last_30d": 22
  },
  "campaigns": [
    {
      "name": "EGM Launch",
      "content_count": 24,
      "by_status": { "published": 17, "scheduled": 5, "draft": 2 },
      "platforms": ["linkedin", "x"],
      "first_post": "2026-04-01T09:00:00Z",
      "last_post": "2026-04-29T16:00:00Z",
      "analytics": {
        "available": true, "window_days": 30, "accounts": 3,
        "totals": { "impressions": 12000, "engagement": 430 },
        "by_platform": [ { "platform": "linkedin", "metrics": { "impressions": 9000 } } ]
      }
    }
  ],
  "analytics": {
    "available": true, "window_days": 30, "accounts": 6,
    "totals": { "impressions": 50000, "engagement": 1800 },
    "by_platform": [ { "platform": "linkedin", "metrics": { "impressions": 30000, "engagement": 1200 } } ]
  }
}
```

> `campaigns` here is the **top 10** by most-recent activity. Use
> `GET /api/v1/campaigns` for the full list.

### 4.2 `GET /api/v1/content`

A paginated list of every post in the workspace (drafts, scheduled, published,
failed). Query params (all optional):

| Param | Type | Notes |
|---|---|---|
| `status` | string | Filter by derived status: `draft`, `scheduled`, `publishing`, `published`, `failed`, `partially_published` |
| `campaign` | string | Exact campaign-label match |
| `platform` | string | Only posts with a child on this platform (e.g. `linkedin`) |
| `source` | `created` \| `curated` | `created` = composer-authored; `curated` = came from the intake register |
| `scheduled_after` | ISO datetime | Lower bound on `scheduled_at` |
| `scheduled_before` | ISO datetime | Upper bound on `scheduled_at` |
| `limit` | int 1–100 | Page size (default `25`) |
| `cursor` | string | Opaque cursor from the previous response |

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/content?status=scheduled&campaign=EGM%20Launch&limit=50" | jq
```

```jsonc
{
  "items": [
    {
      "id": "9a1c…",
      "title": "AfCEN at the EGM",
      "caption_preview": "Join us as African energy leaders convene…",
      "source": "created",
      "status": "scheduled",
      "campaign": "EGM Launch",
      "track": "core",
      "pillar": "energy",
      "platforms": [
        {
          "platform": "linkedin",
          "account_id": "5b2e…",
          "status": "scheduled",
          "scheduled_at": "2026-04-28T08:00:00Z",
          "published_at": null,
          "platform_post_id": "",
          "error": ""
        }
      ],
      "scheduled_at": "2026-04-28T08:00:00Z",
      "published_at": null,
      "created_at": "2026-04-20T10:00:00Z",
      "updated_at": "2026-04-21T11:30:00Z"
    }
  ],
  "next_cursor": "eyJvIjogNTB9",
  "has_more": true
}
```

### 4.3 `GET /api/v1/campaigns`

Every campaign (grouped by the `campaign` label), most-recent activity first.
Optional `days` (7–90, default `30`) for the analytics window. Same
`CampaignSummary` shape as in the overview.

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$HOST/api/v1/campaigns" | jq '.items[].name'
```

### 4.4 `GET /api/v1/pipeline`

Just the funnel — fast, no analytics.

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$HOST/api/v1/pipeline" | jq
```

```jsonc
{
  "stages": [ { "key": "curated", "label": "Curated", "count": 12, "pct": 15, "color": "#e7e5e4" } ],
  "total": 80, "created": 30, "curated": 50, "published": 45, "percent": 62
}
```

---

## 5. Pagination (cursor)

`GET /api/v1/content` is cursor-paginated:

1. Call it with a `limit` (no cursor) for the first page.
2. If the response has `"has_more": true`, pass its `next_cursor` value as the
   `cursor` query param on the next call.
3. Stop when `has_more` is `false` (and `next_cursor` is `null`).

```bash
# page 1
curl -s -H "Authorization: Bearer $TOKEN" "$HOST/api/v1/content?limit=50" > p1.json
NEXT=$(jq -r '.next_cursor // empty' p1.json)

# page 2 (if any)
[ -n "$NEXT" ] && curl -s -H "Authorization: Bearer $TOKEN" \
  "$HOST/api/v1/content?limit=50&cursor=$NEXT" | jq
```

---

## 6. What your key can see (scoping)

Two boundaries shape every response:

- **Workspace wall.** A key only ever sees content and analytics for **its own
  workspace**. There is no cross-house access.
- **Account allowlist.** The key's selected social accounts decide which posts
  and analytics are visible:
  - In `GET /api/v1/content`, a post appears only if **every** platform child it
    targets is on the key's allowlist (drafts that target no account are always
    visible). A post touching an account the key isn't allowlisted on is hidden
    entirely — so give a reporting key all accounts.
  - In `overview`/`campaigns`, analytics totals are summed **only over the key's
    allowlisted accounts**.

**Analytics permission:** the **counts** (pipeline, content, campaign sizes) are
returned for any valid key. The **analytics numbers** require the
`view_analytics` permission. Without it, responses still succeed, but every
`analytics` block reports `"available": false` with empty `totals`. Grant
`view_analytics` to a reporting key.

---

## 7. Rate limits

| Limit | Value |
|---|---|
| Per-key reads (these endpoints) | **300 / minute** |
| Per-key writes (other endpoints) | 120 / minute |
| Per-workspace aggregate | 1000 / minute |

Over-limit requests return **`429`** with a `Retry-After` header and a JSON body:

```jsonc
{ "error": "rate_limited", "tier": "per_key_reads", "limit": 300, "remaining": 0, "retry_after": 12 }
```

`X-RateLimit-Limit` and `X-RateLimit-Remaining` headers are emitted **only on
429 responses**. Back off for `retry_after` seconds.

---

## 8. Error format

All errors share one envelope:

```jsonc
{ "error": "forbidden", "detail": "Permission denied: view_analytics" }
```

| Status | Meaning | Fix |
|---|---|---|
| `401` | Missing/invalid token, or `http://` used | Send a valid `Authorization: Bearer cos_…` over HTTPS |
| `403` | Key lacks a required permission | Re-issue the key with the needed permission |
| `404` | Unknown path | Check the URL (see `/api/v1/docs`) |
| `422` | Bad query param (e.g. malformed `cursor`, `days` out of 7–90) | Fix the parameter |
| `429` | Rate limited | Honour `Retry-After` |

---

## 9. Code examples

### Python (`requests`)

```python
import requests

HOST = "https://web-production-2f84d.up.railway.app"
TOKEN = "cos_your_token_here"
session = requests.Session()
session.headers["Authorization"] = f"Bearer {TOKEN}"

# Overview
overview = session.get(f"{HOST}/api/v1/overview", params={"days": 30}).json()
print("pipeline %:", overview["pipeline"]["percent"])

# Paginate all content
def all_content(**filters):
    cursor = None
    while True:
        params = {"limit": 100, **filters}
        if cursor:
            params["cursor"] = cursor
        page = session.get(f"{HOST}/api/v1/content", params=params).json()
        yield from page["items"]
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]

scheduled = list(all_content(status="scheduled"))
print(f"{len(scheduled)} scheduled posts")
```

### JavaScript (`fetch`)

```javascript
const HOST = "https://web-production-2f84d.up.railway.app";
const TOKEN = "cos_your_token_here";
const headers = { Authorization: `Bearer ${TOKEN}` };

const overview = await fetch(`${HOST}/api/v1/overview?days=30`, { headers })
  .then((r) => r.json());
console.log("published last 30d:", overview.content.published_last_30d);

// Paginate content
async function* allContent(filters = {}) {
  let cursor = null;
  do {
    const qs = new URLSearchParams({ limit: "100", ...filters });
    if (cursor) qs.set("cursor", cursor);
    const page = await fetch(`${HOST}/api/v1/content?${qs}`, { headers }).then((r) => r.json());
    yield* page.items;
    cursor = page.has_more ? page.next_cursor : null;
  } while (cursor);
}
```

---

## 10. Reference

- **Live, always-current schema:** `https://web-production-2f84d.up.railway.app/api/v1/docs`
  (Swagger UI — try requests in the browser with your token).
- **Design & decisions:** `docs/superpowers/specs/2026-06-28-reporting-api-design.md`
- **Implementation:** `apps/api/routers/reporting.py`,
  `apps/composer/api_builders.py`, `apps/analytics/api_builders.py`.
