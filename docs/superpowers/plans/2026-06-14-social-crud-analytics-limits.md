# Social: CRUD + analytics + per-platform limits — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. TDD, one
> commit per task. Tests: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <paths> -q -p no:warnings`.
> Do NOT run the whole suite (slow) — orchestrator does that at the end. Mock all network (httpx) in tests.

**Goal:** Close five gaps the investigation found: (1) enforce per-platform content limits, (2) LinkedIn
delete + edit, (3) Ghost analytics pulling, (4) LinkedIn company follower analytics, (5) token-refresh /
401 hardening so connected accounts survive token expiry.

**Grounding (verified file:line):**
- Per-platform limits DEFINED but NOT enforced: `apps/social_accounts/models.py:97` `PLATFORM_CHAR_LIMITS`;
  `providers/base.py:61` `max_caption_length`; client counter in `templates/composer/compose.html`
  (`char_limits`); NO server/publish validation (`apps/composer/services.py:54`, `apps/publisher/engine.py`).
  Silent truncation in `providers/threads.py:229`, `providers/youtube.py:224`.
- LinkedIn: `providers/linkedin.py` has CREATE only (`publish_post`/`_rest`); no delete/edit/read. Base
  `providers/base.py` has no `delete_post`.
- Ghost: `providers/ghost.py` publish-only; no `get_account_metrics`/post stats; not in
  `apps/analytics/metrics.py:41 PLATFORM_METRICS`. Ghost Admin API exposes members: `GET /ghost/api/admin/members/?limit=1`
  → `meta.pagination.total` (subscriber count). Auth: `self._auth_headers()` (Ghost JWT) already in the provider.
- LinkedIn company analytics: `linkedin_company` IS in `PLATFORM_METRICS` but `get_account_metrics`
  raises NotImplementedError. Follower count via `GET /rest/networkSizes/{orgURN}?edgeType=COMPANY_FOLLOWED_BY_MEMBER`
  or `organizationalEntityFollowerStatistics` (scope-gated: r_organization_social / rw_organization_admin).
- Token machinery EXISTS: `apps/social_accounts/models.py:38-40` (encrypted tokens + token_expires_at),
  `apps/social_accounts/tasks.py:69` (health-check refresh), `apps/publisher/engine.py:450` (pre-publish
  refresh if expiring). GAP: no 401-on-publish refresh-and-retry.

---

### Task 1: Enforce per-platform content limits (server + publish-time)

**Files:** Modify `apps/composer/services.py`, `apps/api/routers/posts.py`, `apps/publisher/engine.py`,
`providers/threads.py`, `providers/youtube.py`. Test: `apps/composer/tests/test_char_limit_enforcement.py`,
`tests/providers/test_limit_enforcement.py` (or nearest existing test modules).

- [ ] **Step 1: Failing tests.** (a) `composer.services.create_post`/`update_post` raises a validation error
  (ValueError or DjangoValidationError) when caption length > `social_account.char_limit`. (b) The API
  `POST/PATCH /api/v1/.../posts` returns 422 for over-limit caption (+ per-account `platform_overrides`).
  (c) `engine._dispatch_to_provider` raises `PublishError` (not silent truncate) when
  `len(content.text) > provider.max_caption_length`, and the PublishLog records it. (d) threads/youtube no
  longer silently truncate — they rely on the engine guard (assert the over-limit raises).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** Add a small helper `validate_caption_length(text, limit, platform)` (in
  `apps/composer/services.py` or a `apps/social_accounts/limits.py`) raising a clear message. Call it in
  create/update service + API routers + engine pre-dispatch. In threads/youtube, remove the
  `[: self.max_caption_length]` silent slice (let the engine guard reject). Keep the existing client counter.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(limits): enforce per-platform caption limits (server + publish-time)`.

### Task 2: LinkedIn delete + edit (delete-recreate)

**Files:** Modify `providers/base.py` (add `delete_post` default raising NotImplementedError),
`providers/linkedin.py` (implement delete), `apps/publisher/engine.py` or a new
`apps/publisher/operations.py` (delete + edit orchestration), `apps/composer/views.py` (+ a delete/edit
action route) + a tiny template hook. Test: `tests/providers/test_linkedin_delete.py`,
`apps/publisher/tests/test_post_operations.py`.

- [ ] **Step 1: Failing tests.** (a) `LinkedInProvider.delete_post(access_token, post_id)` issues
  `DELETE /rest/posts/{urlencoded-urn}` with the versioned REST headers; returns ok on 204/200 and raises
  PublishError on failure (mock httpx). (b) An `delete_published_post(platform_post)` operation calls the
  provider delete and marks the PlatformPost deleted/removed. (c) An `edit_published_post(platform_post,
  new_caption)` operation = delete old + create new, updating `platform_post_id` (LinkedIn has no edit API).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `delete_post` URL-encodes the URN (`urn:li:share:...` / `ugcPost`) and calls
  DELETE with the same auth/version headers `_rest` uses. Operations resolve creds via the existing
  `_resolve_publish_credentials`, call provider delete (then re-publish for edit), and persist state
  transitions on PlatformPost (reuse existing status fields; do not invent a new model unless needed).
  Wire a CSP-safe delete/edit action in the composer post view (Alpine `@click` + `hx-post`, confirm dialog).
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(linkedin): delete + edit (delete-recreate) for published posts`.

### Task 3: Ghost analytics (subscribers + post stats)

**Files:** Modify `providers/ghost.py` (add `get_account_metrics`, optional `get_post_metrics`),
`apps/analytics/metrics.py` (add `ghost` to `PLATFORM_METRICS`), `apps/analytics/tasks.py`
(`BACKFILL_DAYS_PER_PLATFORM` ghost entry), `apps/analytics/constants.py` if needed. Test:
`tests/providers/test_ghost_analytics.py`, `apps/analytics/tests/test_ghost_metrics.py`.

- [ ] **Step 1: Failing tests.** (a) `GhostProvider.get_account_metrics(token, date_range)` returns a metrics
  object/dict with a subscriber/member count from `GET /ghost/api/admin/members/?limit=1` →
  `meta.pagination.total` (mock httpx). (b) `ghost` appears in `PLATFORM_METRICS` with a `followers`-style
  key mapped to members. (c) the analytics sync path resolves the ghost provider without raising
  "no analytics provider".
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `get_account_metrics`: call members endpoint with `self._auth_headers()`, read
  `meta.pagination.total` as the subscriber/follower count; map into the `AccountMetrics` shape the other
  providers return (followers=members). Add ghost row to `PLATFORM_METRICS` (label "Subscribers") + backfill
  config. (Post-level Ghost stats are optional — only if a clean Admin API field exists; else skip, no fake.)
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(ghost): pull subscriber analytics from the Admin API`.

### Task 4: LinkedIn company follower analytics

**Files:** Modify `providers/linkedin_company.py` (implement `get_account_metrics`), `providers/linkedin.py`
if shared. Test: `tests/providers/test_linkedin_company_analytics.py`.

- [ ] **Step 1: Failing test.** `LinkedInCompanyProvider.get_account_metrics(token, date_range)` calls the
  follower-count endpoint (`GET /rest/networkSizes/{orgURN}?edgeType=COMPANY_FOLLOWED_BY_MEMBER` →
  `firstDegreeSize`) with versioned REST headers and returns followers (mock httpx). On 403/insufficient-scope
  it raises the existing insufficient-scope error type so the sync marks `analytics_needs_reconnect` (per
  `apps/analytics/tasks.py:419`), NOT a hard crash.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** Use the org URN from the account (account_platform_id). Map `firstDegreeSize`
  → followers in the AccountMetrics shape. Raise the scope-error type on 403 so the existing reconnect path
  fires. Document that this lights up only once the token has org-read scope.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(linkedin): company follower analytics (scope-gated)`.

### Task 5: Token-refresh + 401 hardening on publish

**Files:** Modify `apps/publisher/engine.py` (`_dispatch_to_provider`). Test:
`apps/publisher/tests/test_publish_401_refresh.py`.

- [ ] **Step 1: Failing test.** When a provider `publish_post` raises an auth/401 error and the account has a
  refresh token, the engine calls `provider.refresh_token(refresh_token)`, updates the account tokens, and
  retries the publish ONCE; on retry-success the post publishes. If there is no refresh token or the retry
  still 401s, the account is marked needs-reconnect (existing status) and the PublishLog records it (mock the
  provider to 401 then succeed).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** Detect a 401/auth failure (PublishError carrying status 401, or an AuthError
  type) in `_dispatch_to_provider`; if `account.oauth_refresh_token` and `provider.auth_type == OAUTH2`,
  refresh + persist + retry once. Reuse the refresh logic already in the health-check task. Mark
  needs-reconnect + stop on terminal auth failure. Keep it OUTSIDE the generic retry/backoff loop (auth retry
  is a single immediate retry, not exponential).
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `fix(publisher): refresh token + retry once on 401, else mark reconnect`.

---

## Self-review
- Build order 1→5 (sequential; tasks touch shared files engine.py / analytics). No agent-service changes.
- After all tasks: full Django suite (deploy gate). Publishing-path changes are higher risk — do NOT
  auto-deploy; the orchestrator returns and the human verifies + deploys.
- Honest limits: LinkedIn follower analytics + token permanence only fully work once the LinkedIn app has
  refresh tokens + org-read scope (external approval). The code is built so it works the moment that lands.
