# Blotato publishing integration — design

> Add-on social publishing via Blotato (single-key, multi-platform API) as a new
> provider family behind the existing compliance gate. Decided via brainstorm
> 2026-06-23. Approach **A** (per-target Blotato providers in the existing registry).

## Goal

Let AfCEN publish to platforms we don't integrate directly — **Instagram,
Facebook, Threads, Bluesky, and personal LinkedIn** — by routing them through
[Blotato](https://help.blotato.com/api/llm), which manages each network's auth on
its side. Existing direct connections (LinkedIn company, X, Ghost) are untouched.
Every Blotato post still goes through our publish gate.

### In scope (MVP)
- Provider family `blotato_{instagram,facebook,threads,bluesky,linkedin}`.
- Workspace-level Blotato API key (credential) + "import accounts from Blotato".
- Gated publish through the existing engine, async-aware (submit → poll →
  reconcile).

### Out of scope (fast-follow)
- TikTok / YouTube / Pinterest (heavy required-metadata tier:
  TikTok privacy+comment flags, YouTube title/privacyStatus, Pinterest boardId).
- Pulling Blotato analytics (`GET /v2/analytics`, `/v2/posts/:id/analytics`,
  `/v2/published-posts`) into our analytics layer.
- In-app OAuth to Blotato-managed networks (Blotato owns that; we import).

## Blotato API contract (verified 2026-06-23)

- Base `https://backend.blotato.com/v2`. Auth header `blotato-api-key: <KEY>`
  (the key may end in `=` base64 padding — send verbatim).
- `GET /users/me/accounts` → `{items:[{id, platform, fullname, username}]}`.
  Company pages: `GET /users/me/accounts/{accountId}/subaccounts` → `pageId`.
- `POST /media` `{filename}` → `{presignedUrl, publicUrl}`; `PUT` binary to
  `presignedUrl`, then use `publicUrl`. (Any already-public URL may be passed
  directly in `mediaUrls` — no upload needed.)
- `POST /posts`:
  ```json
  {"post":{"accountId":"<id>",
           "content":{"text":"...","mediaUrls":[],"platform":"<targetType>"},
           "target":{"targetType":"<targetType>", ...per-platform}},
   "scheduledTime":"<iso8601>"?}
  ```
  `content.platform` MUST equal `target.targetType`. `mediaUrls` required (`[]`
  for text-only). No `scheduledTime`/`useNextFreeSlot` → publishes immediately.
  Returns `postSubmissionId`.
- `GET /posts/{postSubmissionId}` → `{status: in-progress|published|failed,
  publicUrl?, errorMessage?}`.
- Per-target fields used by MVP: **facebook** requires `pageId`; **threads**
  optional `replyControl`; **linkedin** personal = no `pageId` (company would set
  one); **instagram**/**bluesky** none required.
- Rate limits: `POST /posts` 30/min, `GET /posts/:id` 60/min, `POST /media`
  30/min. `429` = exceeded.

## Architecture (Approach A)

A `BlotatoProvider(SocialProvider)` base + thin per-target subclasses registered
under `blotato_*` platform keys. Slots into `PROVIDER_REGISTRY` / `get_provider()`
/ `SocialAccount.platform` with **no change to the publish dispatch contract**
(`publish_post(access_token, content)`), because per-account Blotato data flows
through the engine's existing `content.extra` injection seam.

### Components

1. **`providers/blotato.py`**
   - `BlotatoProvider(SocialProvider)`: `auth_type = AuthType.API_KEY`. Reads
     `api_key` from `self.credentials["api_key"]`. Abstract/overridable
     `target_type` (class attr) + per-platform metadata.
   - `publish_post(access_token, content)`:
     - `account_id = content.extra["blotato_account_id"]` (see seam below).
     - Resolve media: use `content.media_urls` (public) if present; else upload
       each `content.media_files` via `POST /media` (presign → `PUT`) → `publicUrl`.
     - Build target dict: `{"targetType": self.target_type}` + per-platform
       extras (`pageId` from `content.extra["page_id"]` for facebook;
       `replyControl` for threads if set).
     - `POST /posts` (no scheduling → immediate) → `postSubmissionId`.
     - Poll `GET /posts/{id}` every ~2s up to a bounded `BLOTATO_PUBLISH_TIMEOUT`
       (default ~30s): `published` → `PublishResult(platform_post_id=<id>,
       url=publicUrl)`; `failed` → raise `PublishError(errorMessage)`; still
       `in-progress` at timeout → raise `BlotatoStillPublishing(postSubmissionId)`
       (a marker the engine maps to status `publishing`, NOT a retry — see Error
       handling).
   - Subclasses: `BlotatoInstagramProvider`, `BlotatoFacebookProvider`,
     `BlotatoThreadsProvider`, `BlotatoBlueskyProvider`,
     `BlotatoLinkedInProvider` — each sets `target_type`, `platform_name`,
     `max_caption_length`, `supported_media_types`, `supported_post_types`.
   - Registered in `providers/__init__.py::PROVIDER_REGISTRY` under
     `blotato_instagram`, `blotato_facebook`, `blotato_threads`,
     `blotato_bluesky`, `blotato_linkedin`.

2. **Credential resolution** (`apps/publisher/engine._resolve_publish_credentials`)
   - New branch: if `platform.startswith("blotato_")`, load the single
     `PlatformCredential` with `platform="blotato"` for the org (fallback
     `settings.BLOTATO_API_KEY` env) and return `{"api_key": <key>}`. All
     `blotato_*` accounts share one key.

3. **Per-account data** (`apps/social_accounts/models.SocialAccount`)
   - Add `provider_config = models.JSONField(default=dict, blank=True)` (one
     migration). Holds `{"blotato_account_id": "...", "page_id": "..."}` now;
     room for future TikTok/YouTube/Pinterest config. `blotato_account_id`
     duplicates `account_platform_id` for clarity/robustness.

4. **Extras-injection seam** (`apps/publisher/engine`, the existing block that sets
   facebook `page_id` / linkedin_company `author`)
   - New branch: if `platform.startswith("blotato_")`, set
     `extra["blotato_account_id"] = account.provider_config.get(
     "blotato_account_id") or account.account_platform_id` and, for
     `blotato_facebook`, `extra["page_id"] = account.provider_config.get("page_id")`.

5. **Connect / import flow** (`apps/social_accounts`)
   - A "Connect Blotato" screen: paste the workspace Blotato API key → saved as
     the org `PlatformCredential(platform="blotato")` (encrypted).
   - "Import accounts": `GET /users/me/accounts` → list `{id, platform, fullname,
     username}`; user selects which to import → create `SocialAccount`
     (`platform="blotato_"+platform`, `account_platform_id=id`,
     `account_name=fullname`, `account_handle=username`,
     `connection_status=connected`, `provider_config={"blotato_account_id": id}`).
     For `facebook`, call the subaccounts endpoint → store `page_id` in
     `provider_config`. Only import platforms in the MVP set; skip others with a
     note.

6. **Reconcile beat task** (`apps/publisher` + `jobs/schedules.py`)
   - `blotato-reconcile` (every ~1 min): for PlatformPosts left in `publishing`
     with a stored Blotato `postSubmissionId`, `GET /posts/{id}` and finalize to
     `published` (+ url) or `failed` (+ error). Idempotent; never re-submits.

## Data flow

**Publish:** engine poll picks a due `blotato_*` PlatformPost → gate verified at
`_dispatch_to_provider` (unchanged) → `get_provider(platform, {api_key})` →
`publish_post` submits to Blotato + polls → result recorded; on inline timeout the
PlatformPost is parked at `publishing` and the reconcile task finalizes it.

**Connect:** save API key → list Blotato accounts → import selected as
`SocialAccount` rows (+ Facebook pageId).

## Error handling

- **Gate is authoritative** and runs before the provider call — no Blotato bypass.
- `failed` verdict → `PublishError` with Blotato's `errorMessage`; engine marks
  the PlatformPost `failed` (terminal, like any provider failure).
- **Inline timeout (still in-progress)** → park at `publishing` + persist
  `postSubmissionId`; reconcile finalizes. We do **not** raise a retryable error
  here (re-submitting could double-post — Blotato `POST /posts` is not idempotent).
- `429` rate limit → small bounded backoff inside the provider; if still limited,
  treat as a transient retryable publish error (no submission was created, so a
  retry is safe).
- Missing API key / missing `blotato_account_id` → fail closed with a clear error.

## Invariants preserved

- Gate chokepoint unchanged (`apps/publisher/engine`).
- No change to `SocialProvider.publish_post` signature or any existing provider.
- Cross-house wall, content-hash, beat-schedules-single-source all untouched.

## Testing

- Provider unit tests with a mocked Blotato HTTP client: submit→poll→`published`;
  →`failed`; →timeout→`BlotatoStillPublishing`; media upload (presign→PUT→publicUrl)
  vs. public-URL passthrough; per-target payload shape (FB `pageId`, LinkedIn
  personal no pageId, Threads `replyControl`, `content.platform==target.targetType`).
- `_resolve_publish_credentials` blotato branch (PlatformCredential + env fallback).
- Engine extras-injection blotato branch (account_id + FB page_id).
- Reconcile task: parks→finalizes published/failed; never re-submits.
- Import flow: mocked `accounts` (+ subaccounts) → correct SocialAccount rows.
- Use the isolated-DB test pattern (throwaway `config/settings/test_iso.py`,
  `--reuse-db`) to avoid the shared-test-DB overlap.

## Build sequence

1. `provider_config` field + migration.
2. `BlotatoProvider` base + subclasses + registry + types/exceptions
   (`PublishError`/`BlotatoStillPublishing`).
3. Engine: credential-resolution branch + extras-injection branch + `publishing`
   parking on `BlotatoStillPublishing`.
4. Reconcile beat task + schedule.
5. Connect/import flow (API key credential + accounts import UI).
6. Full-suite gate → deploy → set `BLOTATO_API_KEY` / connect in prod → import →
   live test one post per platform.
