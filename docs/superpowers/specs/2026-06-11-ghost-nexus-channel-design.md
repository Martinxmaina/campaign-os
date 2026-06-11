# Ghost (Nexus Brief) Publish Channel — Design Spec

**Date:** 2026-06-11
**Status:** Approved (brainstorming → spec review)
**Scope:** Add Ghost CMS (`the-nexus-brief.ghost.io`) as a first-class publish channel in Campaign OS, behaving like every other platform (connect → compose → schedule → gated publish).

---

## Goal

Let the team connect their Ghost (Nexus Brief) account and publish **human-authored**
content to it — either as a **web post** or an **email newsletter** — composed and
scheduled through the existing Campaign OS flow, gated like every other channel. The
agent assists (the existing "Draft with HERALD") only when a human asks; it never
auto-creates or auto-publishes Ghost content.

## Non-goals (explicitly deferred / out of scope)

- TA.4 Nexus-Brief *pairing* ("LinkedIn + Nexus Brief" twin assets), gated-brief
  companion lifecycle, "teaser blocks until companion live", Wednesday auto-assembly.
- Member-segment targeting for newsletters (publish to *all* members for now).
- Ghost analytics (member counts, opens) — handled in the Analytics Dashboard sub-project.
- Importing/editing existing Ghost posts (we only create + publish new ones).

---

## Architecture — reuse the existing provider pattern

### 1. Platform enum
Add to `apps/credentials/models.py` `PlatformCredential.Platform`:
`GHOST = "ghost", "Ghost (Nexus Brief)"`.
Add `"ghost"` to the composer channel list and `SocialAccount.PLATFORM_CHAR_LIMITS`
(Ghost has effectively no caption limit — use a high value, e.g. 100000).

### 2. Credentials (no OAuth — Admin API key)
In `apps/credentials/platform_fields.py`, register Ghost fields:
- `admin_api_key` — the `id:secret` Admin API key (masked in UI).
- `base_url` — e.g. `https://the-nexus-brief.ghost.io`.
- `newsletter_slug` — optional; required only when publishing as a newsletter.

Saved encrypted through the existing `save_credential(request, platform)` flow.

### 3. Connect → SocialAccount
A "Connect" action (button on the credentials/channels page for Ghost) that:
1. Reads the saved `PlatformCredential` for `ghost`.
2. Validates by calling `GET {base_url}/ghost/api/admin/site/` with a fresh JWT.
3. On success, upserts `SocialAccount(workspace, platform="ghost",
   account_platform_id=<host>, account_name=<Ghost site title>,
   connection_status=CONNECTED)`. On failure → `ERROR` + the Ghost error message.
After connect, Ghost appears in channels, composer, and calendar automatically.

### 4. `providers/ghost.py` — `GhostProvider(SocialProvider)`
- `auth_type = API_KEY` (no OAuth methods).
- **JWT generation** (`_ghost_jwt(admin_api_key)`): split `id:secret`; header
  `{"alg":"HS256","typ":"JWT","kid":id}`; payload `{"iat":now,"exp":now+300,"aud":"/admin/"}`;
  sign with `hmac.new(bytes.fromhex(secret), msg, hashlib.sha256)`, base64url, no padding.
  **Python stdlib only** (`hmac`, `hashlib`, `base64`, `json`, `time`) — no new dependency.
  Generated fresh per request (Ghost tokens expire in 5 min).
- `publish_post(access_token, content)` where `access_token` is the `admin_api_key`:
  - Build post body: `title` = `content.title or first line of caption`,
    `html` = caption/body wrapped as HTML (`<p>…</p>`, newlines → paragraphs),
    `custom_excerpt` = first 280 chars, `status="published"`, `tags=[{"name":"AfCEN"}]`.
  - **Post vs Newsletter** (from `content.extra["ghost_publish_as"]`, default `"post"`):
    - `"post"` → create at `POST /ghost/api/admin/posts/?source=html`, status published, web-only.
    - `"newsletter"` → create at `POST .../posts/?newsletter=<slug>&source=html`,
      then the published post is emailed to members (`email_only` optional — default
      web+email). Requires `newsletter_slug`; if absent → `PublishResult` failure with a
      clear message.
  - Returns `PublishResult(success, post_id, url=<ghost post url>, ...)`. On Ghost API
    error, parse the Ghost error JSON into the failure message; map `INVALID_JWT`/`403`/
    `422 excerpt` to actionable messages.
- `get_profile(access_token)` → validates key, returns `AccountProfile(name=site title)`.
- `get_post_metrics` / `get_account_metrics` → raise/return "not implemented" sentinel
  (Analytics sub-project fills these in).
- Register in `providers/__init__.py` `PROVIDER_REGISTRY["ghost"]`.

### 5. Composer — per-publish Post/Newsletter choice
When the selected channel is Ghost, the composer shows a **"Publish as: Post | Newsletter"**
control. The choice is stored on `PlatformPost` via the existing per-platform options
mechanism (the same `extra`/platform-specific path the engine already reads for
`page_id`/`author`) as `ghost_publish_as`. Default `"post"`.

### 6. Engine — automatic
`apps/publisher/engine.py` already: builds credentials, calls `get_provider(platform,
credentials)`, and runs the **compliance gate before dispatch** for every channel. Ghost
needs only: (a) its credentials assembled (admin_api_key + base_url + newsletter_slug
from `PlatformCredential`), and (b) `content.extra["ghost_publish_as"]` threaded through.
No gate special-casing — Ghost is gated like all outbound.

### 7. Secrets
- **Rotate** the Admin/Content keys currently committed in `docs/ghost.md` (treat as
  compromised once in git). Replace the doc's live values with placeholders.
- Store the new Admin key via the encrypted credential store (per workspace/org).
- Add `GHOST_ADMIN_API_KEY`, `GHOST_BASE_URL`, `GHOST_NEWSLETTER_SLUG` to `.env.example`
  as an env fallback (mirrors `PLATFORM_CREDENTIALS_FROM_ENV` for other platforms).
- Never hardcode keys; never log the secret or full JWT.

---

## Data flow
connect (validate key) → `SocialAccount(ghost)` → human composes Post (optional HERALD
draft assist) → selects Ghost channel + Post/Newsletter → schedule via calendar →
engine: gate → `GhostProvider.publish_post` (fresh JWT → Ghost Admin API) →
`PublishLog` with Ghost post id/url.

## Error handling
- Missing/invalid admin key or base_url → connect fails loudly with Ghost's message;
  publish fails with `PublishResult(success=False, ...)` and the engine's normal retry path.
- `newsletter` chosen but no `newsletter_slug` → publish fails with a clear,
  human-readable error (no silent fallback to web post).
- Ghost `INVALID_JWT` → regenerate (already per-request); `422 excerpt` → 280-char cap
  applied; `403` → "Admin API key required" message.
- Gate block → standard engine behaviour (not published, surfaced to the human).

## Testing (TDD, no live network)
- `_ghost_jwt`: produces a 3-part token; header has `kid`; signature verifies with the
  hex-decoded secret; exp = iat+300.
- `GhostProvider.publish_post` (httpx mocked): post mode hits `/posts/?source=html`;
  newsletter mode hits `/posts/?newsletter=<slug>&...`; newsletter-without-slug → failure;
  title/html/excerpt mapping correct; Ghost error JSON → failure message.
- Connect view (mocked Ghost `/site/`): success creates `SocialAccount`; failure sets ERROR.
- `save_credential` accepts Ghost fields; masking works.
- Engine: a Ghost `PlatformPost` routes through the gate then `GhostProvider`
  (provider mocked); `ghost_publish_as` threaded from `extra`.
- Char-limit + composer channel list include ghost.
- No live network in any unit test; a manual post-deploy smoke publishes one real draft.

## Acceptance
- [ ] Ghost connectable from the credentials/channels page (paste key → validate → account appears).
- [ ] A human-composed post publishes to Ghost as a **web post**.
- [ ] The same flow with "Newsletter" publishes/emails via the configured newsletter slug.
- [ ] Ghost publish passes through the compliance gate (blocked content does not publish).
- [ ] Scheduling a Ghost post via the calendar works like other channels.
- [ ] Leaked keys rotated; `docs/ghost.md` secrets replaced with placeholders; key read
      from the encrypted store / env, never hardcoded.
- [ ] Full fork test suite green; new provider/connect/composer tests pass.
