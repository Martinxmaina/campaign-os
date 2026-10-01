# 06 — Credential Transfer

This document lists every secret Campaign OS needs. For each one it says where the secret is used, how to transfer it and whether to rotate it. **It contains no secret values, and none must ever be added to it**, or to any file, ticket, email or chat message.

## 1. The secure route

1. **AfCEN creates the destination first.** This is a vault in an organisational password manager that AfCEN owns and administers (for example a 1Password Business, Bitwarden Organisation or Keeper shared vault). It must not be the outgoing developer's personal vault. At least two AfCEN staff must be vault admins.
2. **The outgoing owner enters each secret directly into that vault.** Use one vault item per row in §3, with the item title equal to the variable name, and copy values straight from the Railway Variables tab or the provider dashboard.
   - Never paste values into email, WhatsApp, Slack, Teams, Google Docs, this repository or a GitHub issue.
3. **Account logins** (Railway, Blotato, Ghost and so on, §5) are transferred by **adding AfCEN people as owners or admins inside each service**, not by sharing a password. Where a service only supports one login, change the login email to an AfCEN mailbox and store the new password in the vault.
4. **Two-factor authentication:** move every 2FA factor to AfCEN-held devices or the vault's TOTP feature. Store recovery codes in the vault.
5. **Verify out of band.** An AfCEN person confirms receipt on a call. They spot-check that each vault item works, for example by redeploying `web` and checking `/health/` and `/credentials/`.
6. **Rotate** everything marked "Rotate at handover: Yes" in §3, after AfCEN has full access and before the outgoing owner's access is removed. Rotation follows the per-item notes.
7. **Remove** the outgoing owner's access (§6), and record the date in the checklist in [05-accounts-and-access.md](05-accounts-and-access.md) §7.

## 2. Where secrets live today

| Location | What is there |
|---|---|
| Railway → Campaign OS project → `web` and `worker` → Variables | All env vars in §3. **Both services need the same values.** The worker publishes, syncs and sends; the web serves the UI and runs the inline publish. |
| Railway → agent-service project → Variables | agent-service's own secrets (its DB, Azure/DeepSeek keys, JWT signing key, the shared HMAC secret, the ingest key). Not documented in this repo; list them from Railway. |
| Campaign OS database, encrypted | Per-platform app credentials saved in `/credentials/`; every connected account's OAuth access and refresh tokens; per-user Google refresh tokens. These move with the database and stay readable only if `SECRET_KEY` and `ENCRYPTION_KEY_SALT` are kept. |
| Provider dashboards | The master copies of API keys (Blotato, Ghost, DeepSeek, Resend, Google, LinkedIn, Meta, X) |
| Untracked file `docs/ghost.md` on the developer's laptop | Reportedly contained a Ghost key at one point (see [04-known-gaps.md](04-known-gaps.md) G4). Delete it after rotation. |

A scan of all 849 commits on all branches for common key formats (OpenAI-style, Google, GitHub, Slack, Resend, Ghost Admin, private keys) found **no committed secrets** (2026-10-01). CI's gitleaks job reports one finding. It is a false positive: the test-plan line "tokens: mint/resolve/consume; expired + used rejected" in `docs/superpowers/specs/2026-06-25-approval-by-email-design.md:52`, commit `97e6106`. It still makes the gitleaks check fail on every run.

## 3. Environment variables to transfer

**Rotate at handover** means:
- **Yes:** rotate after AfCEN takes ownership, because the value has been held by an individual.
- **Never:** rotating breaks stored data; see the note.
- **Optional:** low risk, or tied to an account that is being transferred anyway.

### 3.1 Core (required to start)

| Variable | Used for | Rotate at handover | Notes |
|---|---|---|---|
| `SECRET_KEY` | Django signing; source key for field encryption and API key hashing | **Never** (without a migration) | Changing it makes every encrypted DB field unreadable, invalidates every API key, logs everyone out and breaks unsubscribe links. Back it up in two places in the vault. |
| `ENCRYPTION_KEY_SALT` | Salt for field encryption and API key hashing | **Never** (without a migration) | Same as above. Missing or empty makes every encrypt and decrypt fail. |
| `DATABASE_URL` | Postgres connection | Optional | Set by Railway's Postgres plugin. Rotate the DB password in Railway if desired; Railway updates the reference. |
| `REDIS_URL` | Celery broker, cache, locks, heartbeat | Optional | Set by Railway's Redis plugin |
| `ALLOWED_HOSTS` | Hostnames Django accepts | — | Not secret. Must include the Railway host and any custom domain. |
| `APP_URL` | Absolute URLs for media sent to providers | — | Not secret |
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` | — | Not secret; the entrypoint defaults to it |
| `PROCESS_TYPE` | `web` or `worker` per service | — | Not secret |

### 3.2 agent-service link

| Variable | Used for | Rotate | Notes |
|---|---|---|---|
| `AGENT_SERVICE_BASE_URL` | agent-service URL | — | Not secret. Currently `https://web-production-e7cf9.up.railway.app` per docs. |
| `AGENT_SERVICE_TOKEN` | Bearer JWT for the dedicated "platform" user in agent-service | **Yes** | Mint a new one by logging in as that user (`POST /auth/login` on agent-service), set it on `web` and `worker`, then restart. Also rotate that user's password in agent-service. |
| `STUDIO_SHARED_SECRET` | HMAC key signing the gate-verify call | **Yes** | Must be identical in agent-service. Change both sides at the same time, or every gated post fails with "gate verify error". |
| `STUDIO_DEPLOYMENT_ID` | Identifier sent with the HMAC | — | Not secret; defaults to `platform`. Must match agent-service. |
| `AGENT_SERVICE_INGEST_URL` | agent-service `/ingest` endpoint | — | Not secret |
| `AGENT_SERVICE_INGEST_KEY` | `X-Ingest-Key` header for `/ingest` | **Yes** | Change in agent-service and here together |

### 3.3 Publishing channels

| Variable | Used for | Rotate | Notes |
|---|---|---|---|
| `BLOTATO_API_KEY` | Blotato publishing, account import, analytics | **Yes** | Blotato dashboard → API key. A `blotato` record in `/credentials/` overrides this for publishing, but analytics always uses the env var (gap G18). Set both or keep them identical. |
| `BLOTATO_API_BASE`, `BLOTATO_PUBLISH_TIMEOUT`, `BLOTATO_POLL_INTERVAL` | Tuning | — | Not secret; defaults are fine |
| `GHOST_ADMIN_API_KEY` | Ghost Admin API (`id:secret`) | **Yes** (see G4) | Ghost Admin → Settings → Integrations → the custom integration → regenerate. Then update the env var and run `python manage.py ensure_ghost_connected`, or update `/credentials/` → Ghost. |
| `GHOST_BASE_URL`, `GHOST_NEWSLETTER_SLUG` | Ghost site and newsletter | — | Not secret |
| `PLATFORM_LINKEDIN_COMPANY_CLIENT_ID` / `_SECRET` | LinkedIn developer app | **Yes** (secret) | LinkedIn developer portal → app → Auth → regenerate the client secret. Connected LinkedIn accounts must reconnect afterwards. Do not set `PLATFORM_LINKEDIN_PERSONAL_*` unless deliberately using OIDC mode (see `docs/operations/linkedin-app-access-request.md`). |
| `PLATFORM_LINKEDIN_PERSONAL_CLIENT_ID` / `_SECRET` | Separate LinkedIn personal app (if used) | **Yes** | As above |
| `PLATFORM_LINKEDIN_CLIENT_ID` / `_SECRET` | Legacy fallback | — | Should be unset |
| `PLATFORM_TWITTER_CLIENT_ID` / `_SECRET` | X developer app (if used) | **Yes** | X developer portal |
| `PLATFORM_FACEBOOK_APP_ID` / `_SECRET` | Meta app: Facebook, Instagram, Threads | **Yes** (secret) | Meta for Developers → app → Settings → Basic → reset the app secret |
| `PLATFORM_INSTAGRAM_APP_ID` / `_SECRET` | Instagram Login app | **Yes** | As above |
| `PLATFORM_GOOGLE_CLIENT_ID` / `_SECRET` | YouTube OAuth client (if used) | **Yes** | Google Cloud Console → Credentials |
| `FACEBOOK_WEBHOOK_VERIFY_TOKEN`, `INSTAGRAM_LOGIN_WEBHOOK_VERIFY_TOKEN`, `YOUTUBE_WEBHOOK_SECRET` | Inbound webhook verification | **Yes** if set | Change in the platform's webhook config at the same time |

Any of these may instead be stored per-platform in `/credentials/`, encrypted in the database. That takes precedence over env vars for publishing. List what is there at handover. The UI shows only the last four characters, so values must come from the provider dashboard.

### 3.4 Google

| Variable | Used for | Rotate | Notes |
|---|---|---|---|
| `GOOGLE_SHEETS_CLIENT_ID` / `_SECRET` | OAuth client for Sheets; also used by every per-user Gmail and Calendar integration | **Yes** (secret) | Google Cloud Console → Credentials → the Desktop client → reset the secret. After a reset, **every** stored Google refresh token issued to that client needs re-consent, including Joseph's and each outreach mailbox. Plan this with the users. |
| `GOOGLE_SHEETS_REFRESH_TOKEN` | The shared token used for sheet sync and the CRM mirror | **Yes** | Re-mint with `scripts/get_google_refresh_token.py`, signed in as an **AfCEN service or shared account** that has access to the sheets, not a personal one. Revoke the old grant in the old account's Google security settings (Third-party access). |
| `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON` | Fallback auth for sheet sync | **Yes** if set | Delete the old key in Google Cloud IAM |
| `GOOGLE_AUTH_CLIENT_ID` / `_SECRET` | "Sign in with Google" | Optional | Google Cloud Console. Redirect URI must match the live host. |
| `CONTENT_INTAKE_SHEET_ID`, `CONTENT_INTAKE_SHEET_RANGE`, `CRM_TRACKER_SHEET_ID`, `CRM_TRACKER_TAB` | Which sheets to use | — | Not secret |

### 3.5 AI and email

| Variable | Used for | Rotate | Notes |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | Direct AI generation (AI Studio, campaign composer) | **Yes** | DeepSeek platform, or Azure AI Foundry → keys. If Azure, also `DEEPSEEK_BASE_URL` (`*.models.ai.azure.com`) and `DEEPSEEK_API_VERSION`. |
| `DEEPSEEK_BASE_URL`, `DEEPSEEK_API_VERSION`, `DEEPSEEK_MODEL` | Endpoint and model | — | Not secret |
| `RESEND_API_KEY` | Approval emails | **Yes** | Resend dashboard → API Keys |
| `DEFAULT_FROM_EMAIL` | Sender address | — | Must be on a Resend-verified domain |
| `EMAIL_BACKEND_TYPE`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_USE_TLS` | SMTP | — | Not secret |
| `EMAIL_HOST_PASSWORD` | SMTP password or app password | **Yes** | Provider dashboard |

### 3.6 Optional and other

| Variable | Used for | Rotate | Notes |
|---|---|---|---|
| `SENTRY_DSN` | Error tracking | Optional | Create a new project in an AfCEN Sentry org and replace the value |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` (+ `S3_ENDPOINT_URL`, `S3_BUCKET_NAME`, `S3_CUSTOM_DOMAIN`, `S3_REGION_NAME`, `STORAGE_BACKEND`) | Media storage, if S3 | **Yes** if set | Create a new key in the bucket provider, update, redeploy, delete the old key |
| `JOSEPH_APPROVER_EMAIL` | Joseph approval gate identity | — | Not secret, but must be correct |
| `WEBHOOK_SECRET` | HMAC for outbound notification webhooks (falls back to `SECRET_KEY`) | Optional | |
| `BB_TRUSTED_PROXIES` | Proxy IPs trusted for client IP | — | Not secret |
| `ENABLE_MOCK_PROVIDER` | Test-only fake channel | — | **Must be false or unset in production** |
| `INTELLIGENCE_*`, `STUDIO_BASE_URL` | Inherited BrightBean billing add-on | — | Should be unset. `STUDIO_BASE_URL` is also used to build outreach unsubscribe links (falls back to the first `ALLOWED_HOSTS` entry). |
| `SITE_NAME`, `SOURCE_REPO_URL` | Branding and AGPL source link | — | Update `SOURCE_REPO_URL` after the repo transfer |

## 4. Secrets stored inside the database

These do not need to be copied separately. They move with the database and are readable as long as `SECRET_KEY` and `ENCRYPTION_KEY_SALT` are unchanged.

| Model and field | Contains | At handover |
|---|---|---|
| `credentials.PlatformCredential.credentials` | Per-platform app keys entered in `/credentials/` | Review the list. Rotate any that the outgoing owner created, using §3 steps, then re-enter them in `/credentials/`. |
| `social_accounts.SocialAccount.oauth_access_token` / `oauth_refresh_token` | Each connected channel's user token | Disconnect any personal test accounts (for example Martin's LinkedIn). Company accounts can stay. |
| `social_accounts.AnalyticsPlatformConfig.client_id` / `client_secret` | Analytics app credentials, if set | Review |
| `joseph.GoogleIntegration.refresh_token` | Per-user Gmail and Calendar consent | Each user can revoke from their Google account; delete rows for people who leave |
| `intelligence.IntelligenceSubscription.intelligence_api_key` | Inherited; should be empty | — |
| `accounts.User.totp_secret` / `totp_recovery_codes` | Unused 2FA fields | — |
| `api_keys.ApiKey.token_hash` | Hashes of issued `cos_…` keys (originals are not recoverable) | Revoke every key issued by the outgoing owner at `/organizations/api-keys/` and issue new ones to the systems that use them |

## 5. Account logins to transfer (by adding AfCEN admins, not by sharing passwords)

| Service | What AfCEN needs |
|---|---|
| GitHub | Ownership of the repo in an AfCEN organisation (and of the agent-service repo) |
| Railway | AfCEN as owner of the team or projects for Campaign OS **and** agent-service; billing on an AfCEN card |
| Azure | Owner role on the subscription or resource group for AI Foundry and Firecrawl |
| Blotato | Account ownership or admin seat; the social logins inside it |
| Ghost(Pro) | Owner role on `the-nexus-brief` site |
| DeepSeek platform | Account login or a new AfCEN account with a new key |
| Resend | Team admin; domain verification |
| Google Cloud | Owner on the project holding the OAuth clients |
| LinkedIn Developer app and Company Page | Two AfCEN admins on each |
| X / Meta developer apps | Admin roles |
| Sentry, S3/R2 (if used) | Org owner |
| Domain registrar and DNS for `africacen.org` / `waiis.org` / email sending domain | Admin access |
| Django `/admin/` superuser | At least two AfCEN superusers (`manage.py createsuperuser`, runbook §4.2) |
| agent-service "platform" user and any agent-service admin users | Credentials in the vault; passwords rotated |

## 6. Removing the outgoing owner's access (after rotation)

Do this only after AfCEN has verified everything works with the rotated values.

1. Railway: remove from team or projects.
2. GitHub: remove from the AfCEN organisation, or reduce to the agreed role.
3. Every service in §5: remove the admin seat or change the login email.
4. Campaign OS: deactivate their user or reduce the role; revoke their API keys; disconnect their personal social accounts; delete their `GoogleIntegration` if they leave.
5. Change workspace setting `review.copy_email` from `martin.maina@africacen.org`.
6. Google: revoke the shared refresh token grant from their Google account if it was minted there (only after the new token is live).
7. Ask them to delete local copies: `.env` files, `docs/ghost.md`, any database dumps, and the Railway CLI login (`railway logout`).
