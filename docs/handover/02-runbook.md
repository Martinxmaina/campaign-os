# 02 — Runbook

How to operate Campaign OS day to day, how to deploy and restart it, and what to do when each known thing breaks.

Railway dashboard steps are given first, then the Railway CLI equivalent. CLI flags change between versions, so check `railway --help` if a command is rejected.

---

## 1. Day 1 checks for the new owner

Do these in order on the first day of ownership. Nothing in the repository proves the production system is still healthy; the last code change was 2026-07-03.

1. **Get into Railway.** Confirm you can see:
   - the Campaign OS project, with services `web`, `worker`, Postgres and Redis;
   - the separate agent-service project.

   Record the project names and IDs in [05-accounts-and-access.md](05-accounts-and-access.md).
2. **Open** `https://web-production-2f84d.up.railway.app/health/`.
   - Expected: `{"status": "ok", "beat": "fresh"}` with HTTP 200.
   - `degraded` means the worker or its scheduler is not running (see §5.1).
3. **Log in** at `/accounts/login/` with an admin account. Then open `/admin/` and check that you are a superuser. If no one at AfCEN has a superuser account, create one (§4.2).
4. **Open `/credentials/`.** Every channel card shows whether credentials are set and which accounts are connected. Note any account showing *Error* or *Token expiring*.
5. **Open Publish → Sent** in a workspace and look for recent failures and their error text.
6. **Open the agent-service health.** Open `https://web-production-e7cf9.up.railway.app/docs` or its health route. Campaign OS cannot publish AI content without it.
7. **Export the env vars.** Export the env var list of each Railway service, names only, and compare it against the list in [06-credential-transfer.md](06-credential-transfer.md). Anything missing is a feature that is off.
8. **Take a database backup** (§3.5) before changing anything.

---

## 2. Normal operation

### 2.1 What runs where

| Railway service | `PROCESS_TYPE` | Start command (from `docker-entrypoint.sh`) |
|---|---|---|
| `web` | `web` (default) | `python manage.py migrate --noinput`, then `python manage.py ensure_ghost_connected` (errors ignored), then `gunicorn config.wsgi:application --workers 2 --threads 2` on `$PORT` |
| `worker` | `worker` | `celery -A config worker -B -l info --concurrency 2` (the `-B` runs the beat scheduler inside the worker) |
| Postgres | — | Railway-managed database |
| Redis | — | Railway-managed Redis |

There is also a `beat` mode (`PROCESS_TYPE=beat`), which is not used in the current setup.

**Rule:** exactly one beat scheduler may run.
- If you ever add a second worker, change the existing worker to run without `-B` and add a dedicated `PROCESS_TYPE=beat` service.
- If two schedulers run, every job fires twice. The publish cycle is protected by a Redis lock, but the daily CRM and outreach jobs are not.

### 2.2 Routine tasks

| Task | Where |
|---|---|
| Add a user | Organisation → Members → Invite (org admin). Invites expire after 7 days. |
| Change a user's role | Organisation → Members → actions menu |
| Connect a Blotato channel | Connect the network inside Blotato (`my.blotato.com`) first, then in Campaign OS: Social accounts → **Import from Blotato** |
| Connect Ghost | Automatic at web start if `GHOST_ADMIN_API_KEY` is set; or `/credentials/` → Ghost → connect |
| Connect LinkedIn personal (direct) | Social accounts → Connect → LinkedIn. It has to be reconnected when the token expires (about 60 days; LinkedIn issues no refresh token in OIDC mode). |
| Change platform app keys without a redeploy | `/credentials/` (stored encrypted in the database; overrides env vars) |
| Issue an API key | `/organizations/api-keys/` (org owner or admin). The `cos_…` token is shown once. |
| Change the email that receives the one-click Send copy | Workspace settings → `review.copy_email`. The default is `martin.maina@africacen.org` (`apps/settings_manager/defaults.py:54`). **Change this at handover.** |
| Change the content-planning sheet | Org setting `intake.sheet_id`, or env var `CONTENT_INTAKE_SHEET_ID`. **The 15-minute job only runs when the env var is set** (see [04-known-gaps.md](04-known-gaps.md)). |
| Force a sheet sync now | Content board → **Sync now** |

---

## 3. Deploying

### 3.1 How code reaches production today

There is **no automatic deployment from GitHub**:
- CI (`.github/workflows/ci.yml`) only runs lint, typecheck, tests, a Docker build and a secret scan. It does not deploy.
- The repo docs say deployment is done from a developer machine with the Railway CLI (`railway up`).
- Whether the Railway services are also linked to the GitHub repo for auto-deploy is **TO CONFIRM** in Railway → service → Settings → Source.

### 3.2 Deploy steps

1. Merge to `main`, and wait for CI to pass.
2. From a checkout of `main`:
   ```bash
   railway login
   railway link            # choose the Campaign OS project
   railway up --service web
   railway up --service worker
   ```
   Deploy **both** services. They run the same image, and a worker on old code alongside web on new code can fail on changed models or tasks.
3. Migrations run automatically when `web` starts. Watch the `web` deploy log for `Applying …` lines or a migration error.
4. Check `/health/` and log in.

### 3.3 Rolling back

- **Railway dashboard:** service → Deployments → pick the previous successful deployment → **Redeploy**. Do it for both `web` and `worker`.
- If the bad release included a migration, rolling back the code does **not** undo the database change. Either write a reverse migration, or restore the backup taken before the deploy (§3.5).

### 3.4 Adding a dependency

Add it to **`requirements.txt`** (production uses pip with this file). Adding it only to `pyproject.toml` means it will not be installed in production.

### 3.5 Database backup and restore

- Railway Postgres has a Backups tab on paid plans. Whether backups are enabled is **TO CONFIRM**.
- To take a manual dump, take the public connection string (`DATABASE_PUBLIC_URL`) from the Postgres service's Variables tab and run:
  ```bash
  pg_dump "$DATABASE_PUBLIC_URL" -Fc -f campaign_os_$(date +%F).dump
  # restore into an empty database:
  pg_restore --no-owner -d "$TARGET_DATABASE_URL" campaign_os_YYYY-MM-DD.dump
  ```
- **A database dump is useless without the matching `SECRET_KEY` and `ENCRYPTION_KEY_SALT`.** All tokens and credentials in it are encrypted with keys derived from those two values. Store the two values with the backups, through the secure route in [06-credential-transfer.md](06-credential-transfer.md).

---

## 4. Restarting and one-off commands

### 4.1 Restart

| What | Dashboard | CLI |
|---|---|---|
| Web app | `web` → Deployments → latest → **Restart** | `railway redeploy --service web` |
| Background jobs and scheduler | `worker` → Restart | `railway redeploy --service worker` |
| Redis | Restarting Redis drops queued jobs. Scheduled posts are safe because they live in Postgres; the publish cycle picks them up again within 15 s. Restart the worker afterwards. | |
| Postgres | Avoid. Restart only if Railway reports it unhealthy, then restart `web` and `worker`. | |

`railway.toml` restarts a crashed service automatically, up to 5 times (`restartPolicyType = "on_failure"`). After five failures it stays down until someone acts.

### 4.2 Running management commands against production

The pattern documented in `apps/crm/management/commands/seed_demo.py` runs the command on your machine with production's environment, against the database's public URL:

```bash
railway run --service web -- bash -c 'DATABASE_URL=$DATABASE_PUBLIC_URL python manage.py <command>'
```

This needs a local checkout with dependencies installed (`uv sync` or `pip install -r requirements.txt`). Recent Railway CLIs also offer `railway ssh --service web`, which opens a shell inside the running container. There you can run `python manage.py <command>` directly.

Useful commands:

| Command | Purpose |
|---|---|
| `createsuperuser` | Create an admin login |
| `shell` | Django shell, for the data fixes in §5 |
| `ensure_ghost_connected` | Recreate or refresh the Ghost channel from `GHOST_ADMIN_API_KEY` |
| `run_approval_reminders` | Send stalled-approval reminders once (not scheduled; see gaps) |
| `run_inbox_sync --once` | Poll social inboxes once (not scheduled) |
| `cleanup_orphaned_media --once --dry-run` | List unused media files; drop `--dry-run` to delete |
| `backfill_analytics --account-id <id> --days 30` | Re-pull analytics for one account |
| `backfill_post_segments` | Copy track, pillar and campaign from intake items onto posts |
| `import_threads_from_agent_service --dry-run` | One-off: import CRM threads from agent-service |
| `seed_demo --owner <email>` / `--wipe` | Load or remove demo CRM data. **Do not run in production** unless you intend to. |
| `seed_blocks` | Load the deck content-block library |
| `clearsessions` | Delete expired login sessions (not scheduled on Railway) |

---

## 5. What breaks and what to do

Each entry gives the symptom, the cause and the fix.

### 5.1 `/health/` returns `degraded` / 503

- **Cause:** no heartbeat in Redis for 3 minutes. Either:
  - the `worker` service is down or crash-looping,
  - Redis is down, or
  - `REDIS_URL` is missing on `web` or `worker`. Without it each process uses its own private cache, so `/health/` can never see the heartbeat.
- **Fix:**
  1. Open the worker logs. Look for import errors or `Connection refused` against Redis.
  2. Check that `REDIS_URL` is set on both services.
  3. Restart the worker.
- While this is broken, **nothing publishes** and no sync runs.

### 5.2 Scheduled posts are not going out (stay "Scheduled")

1. Check `/health/` (above).
2. Check the worker log for `publish-cycle` lines. `LockNotAcquired` every 15 s for more than 10 minutes means a stuck lock or a stuck cycle. Restart the worker; the lock expires after 600 s on its own.
3. If the post has a `next_retry_at` in the future, it is waiting for its retry (1 min, then 5 min, then 30 min).

### 5.3 Post failed with `GATE BLOCK: missing gate_id`

- **Cause:** the post was created by AI or HERALD and then published through **Send**, **Approve & publish**, or the composer's publish button. None of these paths asks the gate for a `gate_id` (known bug G1 in [04-known-gaps.md](04-known-gaps.md)).
- **Fix:** publish it from **Console → Drafts → Publish/Schedule** (`apps/composer/console_publish.py`). That path calls the gate and stamps the `gate_id`.
- **Do not** "fix" it by opening and saving the post in Compose. Compose marks the post as human-written and skips the compliance check entirely.

### 5.4 Post failed with `GATE BLOCK: gate verify error …`

- **Cause:** Campaign OS could not reach agent-service, or the signature was rejected.
- **Check:**
  1. agent-service is up.
  2. `AGENT_SERVICE_BASE_URL` is correct.
  3. `STUDIO_SHARED_SECRET` and `STUDIO_DEPLOYMENT_ID` match the values agent-service expects.
  4. The clocks of the two services agree; the HMAC includes a timestamp.
- **Fix:** then re-publish.

### 5.5 Post failed with `GATE BLOCK: content hash mismatch` or `gate verdict block/flag`

- **Hash mismatch** means the text changed after it was gated. Re-run it through Console → Drafts so it is gated again.
- **Block/flag** means the compliance gate rejected the wording. Edit the content to remove the flagged phrase (for example "secured", "committed" or "confirmed" without a signed source, or a confidential keyword) and gate again.

### 5.6 Post is "Pending client" with `[JOSEPH GATE]`

- **Cause:** the content targets a Joseph-personal channel and Joseph has not approved it.
- **Fix:** Joseph approves it in Approvals.
  - If the approval is recorded under a different email than expected, check `JOSEPH_APPROVER_EMAIL` (env var) and the intake item's owner email.
  - This is intended behaviour, not a fault.

### 5.7 Post failed: intake gate (`private_hold`, `confidential`, `needs_verification`, open condition)

- **Cause:** the source row in the planning sheet is marked sensitive, or has an unblock condition (partner permission, figure confirmation, hold-until date).
- **Fix:** resolve it at the source.
  - Change the sheet row; the next sync picks it up.
  - Or close the condition on the Content board (Conditions → Close).
- This is intended. Unknown sensitivity text in the sheet is treated as `private_hold` on purpose.

### 5.8 A Blotato channel shows "Error" / "connection has expired" / code 5002

- **Cause:** the social network's login inside Blotato expired.
- **Fix:**
  1. Log in to `my.blotato.com` and reconnect that network.
  2. In Campaign OS, run Social accounts → **Import from Blotato**. This is required: the account's error status **does not clear on its own** after a successful publish, and error accounts are skipped by health checks. The import resets it to Connected.
  3. Re-schedule the failed posts.

### 5.9 Blotato posts stuck on "Publishing"

- **Normal behaviour:** Blotato publishes asynchronously, and the `blotato-reconcile` job checks every 60 s.
- **If stuck for more than 10 minutes:** check the worker is running. Then look up the submission in Blotato's dashboard.
- **Known limitation:** after reconcile marks a post published, the published URL is not stored.

### 5.10 A non-Blotato post stuck on "Publishing"

- **Cause:** the worker was killed mid-publish. No job recovers these.
- **Fix:**
  1. Check on the platform whether it actually went out.
  2. Fix it from a Django shell (§4.2). PlatformPosts are not in Django admin.
   ```python
   from apps.composer.models import PlatformPost
   pp = PlatformPost.objects.get(id="<uuid>")
   # If it did NOT go out:
   pp.status = PlatformPost.Status.SCHEDULED; pp.save(update_fields=["status"])
   # If it DID go out, mark it published and record the URL:
   # pp.status = PlatformPost.Status.PUBLISHED; pp.published_url = "https://..."; pp.save()
   ```

### 5.11 Direct LinkedIn account asks to log in again / posts fail with 401

- **Cause:** expected roughly every 60 days in OIDC mode.
- **Fix:** reconnect from Social accounts.
- **Permanent fix:** get LinkedIn's Community Management API approved and switch to company-app credentials. Follow `docs/operations/linkedin-app-access-request.md` step by step.

### 5.12 Content board stops updating from the Google Sheet

1. Check `CONTENT_INTAKE_SHEET_ID` is set on the **worker** service. The 15-minute job silently does nothing without it.
2. Check the worker log for Google errors such as `invalid_grant`. That means the refresh token was revoked or expired. Two common causes:
   - the Google account changed its password;
   - the OAuth consent screen is in "Testing" mode, where Google expires refresh tokens after 7 days.
3. Mint a new token:
   ```bash
   pip install google-auth-oauthlib
   python scripts/get_google_refresh_token.py
   ```
   Sign in as the Google account that can open the sheet. Put the printed `GOOGLE_SHEETS_REFRESH_TOKEN` (and client ID and secret, if changed) on **both** `web` and `worker`, then restart both.
   - The same token powers the CRM sheet mirror.
   - The script requests read-write Sheets, Calendar read, Gmail read and Gmail send scopes.
4. If the sheet's tab was renamed, the sync auto-detects the first tab. Check that `CONTENT_INTAKE_SHEET_RANGE` still covers columns A–P.

### 5.13 AI Studio / campaign composer returns a placeholder ("Once the DEEPSEEK_API_KEY is set …")

- **Cause:** `DEEPSEEK_API_KEY` is missing, invalid or out of credit, or the model returned nothing. The client never raises an error; it returns empty text.
- **Fix:** check the worker and web logs for `deepseek` warnings and the provider's billing page. Fix the key, then redeploy or restart `web`.

### 5.14 HERALD drafts, briefs, dossiers, wiki or the `/console/brain` pages show "unavailable"

- **Cause:** agent-service is down or `AGENT_SERVICE_TOKEN` has expired.
- **Fix:** the token is a JWT for a dedicated "platform" user in agent-service. Mint a new one by logging in as that user (`POST /auth/login` on agent-service, per `docs/platform-console-deploy.md`). Set it as `AGENT_SERVICE_TOKEN` on both services and restart.

### 5.15 Outreach "Send" returns a server error (500), or daily sequence emails stop

- **Cause:** most likely agent-service is unreachable. The outreach code does not catch the gate's connection error (bug G3 in [04-known-gaps.md](04-known-gaps.md)).
- Nothing is sent, so there is no compliance risk.
- **Fix:** restore agent-service, then press Send again. The daily `outreach-advance` job retries the next day.
- **Other causes:** a mailbox without the `gmail.send` scope fails with a clear "scope" message. Re-run the Google token script for that user to fix it.

### 5.16 Approval emails are not arriving

The emailer tries three transports in order:
1. Resend (`RESEND_API_KEY`; `DEFAULT_FROM_EMAIL` must be on a domain verified in Resend),
2. the first connected Gmail integration with send scope,
3. SMTP (`EMAIL_HOST*`).

**Fix:** check the web log for `emailer` warnings, then check each transport.

Other notification emails (invites, password reset, in-app notification emails) use **SMTP only**. If `EMAIL_BACKEND_TYPE` is not `smtp`, they are printed to the log and never sent.

### 5.17 Ghost posts fail

- **Check:**
  - `GHOST_ADMIN_API_KEY` is still valid (Ghost Admin → Settings → Integrations).
  - `GHOST_BASE_URL` is right.
  - For newsletter sends, `GHOST_NEWSLETTER_SLUG` matches a newsletter. If it is empty, Ghost's oldest newsletter is used.
- **Fix:** run `python manage.py ensure_ghost_connected` after changing the key.

### 5.18 Everything encrypted suddenly fails ("Decryption failed - possibly wrong SECRET_KEY")

- **Cause:** `SECRET_KEY` or `ENCRYPTION_KEY_SALT` was changed or lost.
- **Effects:**
  - every stored OAuth token, platform credential and Google refresh token becomes unreadable;
  - every API key stops working;
  - every unsubscribe link breaks.
- **Fix:** put the old values back. There is no re-encryption tool. **Never rotate these two values** without first writing a migration that decrypts and re-encrypts every encrypted field (listed in [06-credential-transfer.md](06-credential-transfer.md) §4).

### 5.19 Deploy fails at build

- **Check the build log first.** Common causes:
  - **Tailwind / npm:** `npm ci` in `theme/static_src`.
  - **`collectstatic`:** a template or static reference error.
  - **A package missing from `requirements.txt`.**
- The image builds `collectstatic` with a placeholder `SECRET_KEY` and SQLite, so build failures are code problems, not env problems.

### 5.20 Deploy fails at start with a migration error

- The `web` service stops before gunicorn starts, and the site is down.
- **Fix:** read the migration error in the deploy log. Roll back the code (§3.3), fix the migration, and redeploy. Do not delete migration files that have already run in production.

### 5.21 Someone unknown has an account

- **Cause:** signup is open to anyone, and every new account is made **Owner** of the AfCEN organisation (bug G2 in [04-known-gaps.md](04-known-gaps.md)).
- **Fix:**
  1. Remove the user in Members, or deactivate them in `/admin/` (`is_active` off).
  2. Review what they changed: API keys issued, credentials and channels, members.
  3. Fix the bug (G2) as the first engineering task after handover.
