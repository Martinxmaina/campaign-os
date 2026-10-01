# 04 — Known Gaps, Bugs and Unfinished Work

Everything below was found by reading the code on 2026-10-01. Each item gives the file and line so it can be checked. They are grouped by severity:
- **Fix first:** security or data-integrity risk.
- **Broken:** a feature that does not work as users would expect.
- **Not built:** a placeholder or a missing part.
- **Housekeeping:** leftovers that create confusion or risk later.

---

## A. Fix first

### G2. Anyone can sign up, and every new account becomes Owner of AfCEN
- `/accounts/signup/` is open to the public. There is no domain allowlist and no invite-only setting, and email is never verified (`ACCOUNT_EMAIL_VERIFICATION = "none"`).
- A `post_save` signal (`apps/accounts/signals.py:144`, `provision_organization_and_workspace`) adds **every** new user to the single "AfCEN" organisation and "WAIIS" workspace as **Owner** at both levels (lines 36–54).
- A stranger who finds the URL gets full control. That includes:
  - connected social channels,
  - stored credentials,
  - API key issuance,
  - members,
  - CRM data.
- **Fix:** close signup, either with an allauth account adapter whose `is_open_for_signup` returns False except for invite tokens, or with a domain allowlist. Change the signal so non-invited users get no role, or the lowest role.
- **Until fixed:** review Members regularly (runbook §5.21).

### G4. Secrets may have leaked into an untracked file
- `.claude/wf-ghost.js` (a development workflow script, committed to the repo) contains a task saying secrets had leaked into an untracked `docs/ghost.md` and should be rotated or redacted.
- That file is in `.gitignore` and is not in the repository.
- Nothing in the repo proves the Ghost Admin API key was rotated afterwards.
- **Action:** rotate the Ghost Admin API key at handover regardless (see [06-credential-transfer.md](06-credential-transfer.md)).

### G5. The source code is in a personal GitHub account
- The repo is `github.com/Martinxmaina/campaign-os`, a personal account, and all 81 commits are authored with a personal Gmail address.
- `SOURCE_REPO_URL` and the `/about/` page point to `https://github.com/africacen/campaign-os`. Whether that exists is **TO CONFIRM**.
- **Action:** transfer the repository to an AfCEN-owned GitHub organisation. Make sure the AGPL source link on `/about/` points to a repository that exists and is public (the AGPL §13 obligation). Fill in the placeholder in `NOTICE` ("`<this fork's repository URL>`").

### G6. The agent-service source code is not in this repository and its location is unrecorded
- Campaign OS cannot publish AI content, send outreach, show briefs or run the compliance gate without agent-service.
- The repo docs only mention a local path on the developer's laptop: `/Users/macbook/Downloads/WAIIS/agent-service`. No Git URL is recorded anywhere.
- **Action:** before handover is signed off, the agent-service repository, its Railway project and its database must be located and transferred under the same terms as this repo.

### G7. Rotating `SECRET_KEY` or `ENCRYPTION_KEY_SALT` destroys stored credentials
- All encrypted fields are AES-256-GCM with a key derived from these two values (`apps/common/encryption.py`). API key hashes use the same derivation (`apps/api_keys/services.py`).
- There is no re-encryption tool. Losing or changing either value makes every stored token unreadable.
- **Action:** treat these two values as the most important secrets in the system. Back them up through the secure route.

---

## B. Broken behaviour

### G1. AI-approved posts sent with "Send" or "Approve & publish" are blocked at publish
- Posts built from AI content by `apps/approvals/intake_publish.py` have no `gate_id` and `gate_bypassed=False`.
- These three paths all call `schedule_now()` (`apps/composer/views.py:570`), which never asks the gate for a `gate_id`:
  - **Send** (`apps/approvals/send_actions.py:60`),
  - review-page **Approve & publish** (`apps/approvals/review_views.py:150`),
  - the composer publish button (`apps/composer/views.py:1057`).
- At publish time the engine returns `GATE BLOCK: missing gate_id` (`apps/publisher/engine.py:330`) and the post fails.
- The only production code that stamps a `gate_id` is `apps/composer/console_publish.py:56-80` (Console → Drafts publish) and the REST API.
- **Workaround:** runbook §5.3.
- **Fix:** have `schedule_now` (or `send_for_publish`) call `check_gate` and stamp `gate_id` and `content_hash` the way `console_publish` does, for posts that are not `gate_bypassed`.

### G3. Outreach crashes instead of failing cleanly when agent-service is down
- `check_gate` raises `GateError`, which is not a subclass of `OutreachError`. These three places catch only `GateBlocked` and `OutreachError`:
  - `apps/outreach/gating.py::send_email`,
  - `apps/outreach/sequences.py:121-128`,
  - `apps/outreach/views_thread.py:113-121`.
- **Result:**
  - the Send button returns HTTP 500;
  - the daily `advance_sequences` job stops at the first failing step, so the remaining due steps that day are not processed;
  - no error is recorded on the step.
- Nothing is sent, so there is no compliance leak.
- **Fix:** catch `GateError` in those three places. The decks module already does this (`apps/decks/assembly.py:274`).

### G8. Calendar sync can wipe meeting-to-thread links
- `apps/joseph/tasks.py::sync_google_calendar` (every 5 minutes) matches calendar events against **agent-service** thread IDs. It then writes the result into `CalendarEvent.linked_thread_id` with `update_or_create` (lines 191–204).
- It writes `""` whenever there is no confident match. That includes every event when agent-service is unreachable, and events Joseph linked by hand (`apps/joseph/linkage.py`).
- The rest of the Joseph code treats `linked_thread_id` as a **Django CRM thread** ID, so even a successful auto-link points at the wrong kind of ID:
  - `meeting_prep.py:201-213`,
  - `capture.py:214-222`,
  - `linkage.py:125-143`.
- **Fix:**
  - match against `apps.crm.OutreachThread`;
  - only write `linked_thread_id` when a new link is found;
  - never overwrite a manual link.

### G9. Editing a published post skips the gate
- `apps/publisher/operations.py::edit_published_post` deletes and re-creates the post on the platform by calling the provider directly, with no gate check.
- **Fix:** route edits through the engine, or call `check_gate` first.

### G10. Deleting a published post can return a 500
- `apps/composer/views.py:1072` (`platform_post_operation`) catches only `ProviderError`.
- Blotato and direct X providers have no `delete_post`, so they raise `NotImplementedError`, which is not caught.
- Delete only works for Ghost and LinkedIn (commit `0242c94`).

### G11. Blotato accounts flagged "Error" never recover on their own
- `_mark_needs_reconnect` sets `connection_status=ERROR`.
- No code sets it back on a successful publish, even though the UI message in `apps/social_accounts/views.py:678-680` says it will.
- Health checks only look at CONNECTED and TOKEN_EXPIRING accounts.
- **Workaround:** run **Import from Blotato** again (runbook §5.8).

### G12. Blotato reconcile leaves fields unset
- `apps/publisher/tasks.py:61-78` marks the post published. It does not:
  - save `published_url`,
  - update the parent post's `published_at`,
  - send the `/ingest` event.
- Posts that finished through reconcile have no link in the Sent view.

### G13. No recovery for posts stuck in "Publishing"
- If the worker dies mid-publish on a non-Blotato channel, the row stays `publishing` forever. No sweeper exists.
- **Workaround:** runbook §5.10.

### G14. Human-composed posts never get their first comment
- `_post_first_comment_task` exits with "parent has no gate_id" (`apps/publisher/engine.py:1119-1123`).
- Composer posts are `gate_bypassed` and have no `gate_id`, so the first-comment field in Compose silently does nothing for them.

### G15. Two daily CRM jobs overwrite each other's traffic light
- `score_all_threads` sets `traffic_light` from the score quintile. `flag_no_reply` sets it from days since last contact (`apps/crm/tasks.py:75-121`).
- Both run daily in no fixed order, so the colour shown depends on which ran last.

### G16. Sheet sync only runs automatically when the env var is set
- `sync_all_intake_sheets` exits early unless `CONTENT_INTAKE_SHEET_ID` is set in the environment.
- A sheet configured only through the org setting `intake.sheet_id` is synced only with the manual **Sync now** button.

### G17. Joseph voice save can erase audience hooks
- `voice_save` (`apps/joseph/views.py:1234-1238`) re-reads `hooks_by_audience` from agent-service.
- If that read fails, the following save sends `{}` and wipes the field.

### G18. Inbox and analytics ignore credentials stored in `/credentials/` for some paths
- **Inbox:** sync and reply call `get_provider(account.platform)` with no credentials (`apps/inbox/tasks.py:37`, `apps/inbox/views.py:228`), so only env-var app credentials work.
- **Analytics:** for `blotato_*` accounts, analytics looks up a credential named `blotato_linkedin` and so on, not `blotato`. It therefore depends on the `BLOTATO_API_KEY` env var.

### G19. Platform values the model does not list
- `twitter` and `blotato` are saved as `PlatformCredential.platform` values but are not in the model's choices (`apps/credentials/models.py:10-29`).
- Saving works because no validation runs. Editing those rows in Django admin will fail validation.

### G20. `blotato_import` has a weaker permission check
- `apps/social_accounts/views.py:805` uses `@login_required` only.
- The other account views require the `manage_social_accounts` permission.

### G21. Pinterest board picker calls a provider that was removed
- `apps/composer/views.py:1435` (`pinterest_boards`) calls `get_provider("pinterest")`, which raises `ValueError`.
- Pinterest, TikTok, Mastodon and direct Bluesky remain in database choices and some views, but their providers were deleted (`docs/ADR-002-upstream-pin.md`, Task 3).

---

## C. Not built (placeholders and unscheduled code)

### C1. Jobs that exist but never run (not in `jobs/schedules.py`)

| Function | What it would do | How to run it today |
|---|---|---|
| `apps/approvals/tasks.py::check_approval_reminders` | Remind reviewers after 24 h / 48 h, then escalate | `manage.py run_approval_reminders` |
| `apps/inbox/tasks.py::InboxSyncEngine` | Poll social inboxes and check SLAs | `manage.py run_inbox_sync --once` |
| `apps/notifications/tasks.py::retry_failed_deliveries` | Retry failed email and webhook notifications | none |
| `apps/notifications/tasks.py::send_daily_digests` | Daily digest emails | none |
| `apps/calendar/tasks.py::generate_recurring_posts` | Recurring posts. If enabled as-is, its posts would be blocked by the gate (no `gate_id`, no bypass). | none |
| `manage.py cleanup_orphaned_media` | Delete unused media files | manual |
| `manage.py clearsessions` | Delete expired sessions | manual (the old docker-compose `maintenance` service ran it; Railway does not) |
| `PublishLog` 90-day cleanup | Mentioned in the model docstring; not written | — |
| Revoked API key deletion | `apps/api_keys/views.py:343` says a background sweep deletes them; none exists | — |

### C2. Placeholders marked "SEAM" or "stub" in code

| Feature | File | Current behaviour |
|---|---|---|
| Voice-note transcription | `apps/joseph/transcription.py` | Returns the stored transcript or `"[transcript pending …]"`; no speech-to-text service is called |
| Meeting-note extraction | `apps/joseph/extraction.py` | Keyword heuristic, not the planned agent pass |
| Joseph "Ask" | `apps/joseph/intelligence.py:265` | Stub |
| Talking-point gate terms | `apps/joseph/talking_points.py:29` | Hard-coded word list copied from agent-service rules |
| Deck voice pass | `apps/decks/voice.py` | Returns input unchanged |
| Deck section edits | `apps/decks/edits.py` | Placeholder |
| Google Slides output | `apps/decks/slides.py` | Returns a fake URL `https://docs.google.com/presentation/d/slides-<id>/edit`; no Slides API call |
| Request deck / Capture from the Joseph pipeline | `apps/joseph/views.py:643-648, 732` | "present-but-stubbed" |
| Instantly email transport | `apps/outreach/senders.py:62-66` | Raises `NotImplementedError` |
| Eval suites | `apps/evals/runner.py` | No URL, task or command runs them. Non-dry runs mark every non-compliance case as passed. |
| Sheet write-back | `config/settings/base.py:275-282` | Not implemented; the flag is unused |
| Direct X OAuth, media and analytics | `providers/twitter.py:6, 163` | Text only; cannot be connected from the UI |
| Direct LinkedIn personal analytics and first comment | `providers/linkedin_personal.py:69-82` | Not possible without LinkedIn Community Management API approval |
| Blotato delete, comments, inbox, account metrics | `providers/blotato.py` | Not implemented |
| Blotato LinkedIn page ID | `providers/blotato.py`, comment near line 253 | "verify on the first real page publish". `blotato_import` only fetches page IDs for Facebook (`apps/social_accounts/views.py:821-824`). |
| Google integration connect flow | — | No screen creates `joseph.GoogleIntegration` rows (Gmail/Calendar per user). They have to be created in admin or a shell with a refresh token from `scripts/get_google_refresh_token.py`. |
| Two-factor authentication | `apps/accounts/models.py:34-37` | Database fields exist; no enrolment or verification screens. The org setting `org.2fa_enforcement` is not wired. |
| Analytics historical backfill | `apps/analytics/tasks.py:582` | Deferred |

### C3. Roadmap items from the README not started
From `README.md` "Build status":
- 2B+: pre-meeting cascade polish, post-meeting voice capture, decks, data-room signals.
- 2C+: grant scanning (FORGE), deliberation with CRM context.
- Phase 3 (WAIIS summit) and Phase 4 (hardening).

The full design intent is in `docs/phase2.md`, `docs/joseph.md` and `docs/superpowers/specs/`.

---

## D. Housekeeping

| Item | Detail |
|---|---|
| Two failing tests | See [README.md](README.md). Fix the 280→25,000 expectation and commit the fixture image, or create it in the test. |
| Python version mismatch | `.python-version`/`pyproject.toml` require 3.13; the `Dockerfile` and CI use 3.12. Production works because it installs from `requirements.txt` with pip. Pick one. |
| Dependency lists drift | `requirements.txt` (used in production) and `pyproject.toml`/`uv.lock` (used locally) are maintained separately. `openai` is in `requirements.txt` but not `pyproject.toml`. |
| BrightBean leftovers | `app.json`, `render.yaml`, `SECURITY.md` (`security@brightbean.xyz`), `CONTRIBUTING.md`, `.github/CODEOWNERS` (`@JanSchm`), `.github/ISSUE_TEMPLATE/config.yml`, `package.json`, favicon manifest, docker-compose DB names. Replace or delete. |
| Do **not** rename | The strings `brightbean-field-encryption` and `brightbean-api-key-hmac` in `apps/common/encryption.py` and `apps/api_keys/services.py`. They are part of the key derivation. |
| Site domain record | Migration `apps/accounts/migrations/0005_set_site_campaign_os.py` sets the Django Site to `app.waiis.org`. Whether that domain exists or is owned by AfCEN is **TO CONFIRM**. |
| Hard-coded personal email | `review.copy_email` default `martin.maina@africacen.org` (`apps/settings_manager/defaults.py:54`) |
| Hard-coded names | Pillar owners in `apps/content_intake/owner_routing.py` (by first name) |
| Dev-machine paths in repo | `.claude/wf-ghost.js`, `docs/ADR-002-upstream-pin.md` (`/Users/macbook/...`). Harmless, but `.claude/` can be removed. |
| Inherited billing code | `apps/intelligence` (Stripe-backed BrightBean "Intelligence") is installed but switched off. Its two scheduled jobs are no-ops. It can be removed once its migrations are no longer needed. |
| README claims | "No bypass route" for the gate is inaccurate (see [01-system-overview.md](01-system-overview.md) §4.2); the test count is out of date. |
| Production CSRF | `CSRF_TRUSTED_ORIGINS` is only read in development settings. If a custom domain is added behind a proxy, check that form posts still pass CSRF. |
| Rate-limit IP trust | `AuthRateLimitMiddleware` trusts the first `X-Forwarded-For` value without checking, so the login rate limit can be bypassed by spoofing the header. |
