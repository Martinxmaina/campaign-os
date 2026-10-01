# 03 — Monitoring and Alerting

## 1. The short answer

**There is no active alerting set up in this repository.**
- No uptime monitor is configured.
- No error-tracking DSN is committed.
- No `ADMINS` / `mail_admins` is configured.
- No job sends an alert when publishing fails.

When something breaks today, it is noticed by:
- a user seeing an error on screen,
- someone checking **Publish → Sent**, or
- someone reading the Railway logs.

The rest of this document lists exactly what does exist, who it reaches today, and what to set up.

## 2. What exists

### 2.1 Health endpoint — `/health/`

- **Code:** `apps/accounts/views.py::health_check`; route `config/urls.py:14`.
- **Response:**
  - `{"status": "ok", "beat": "fresh"}` with HTTP 200 when the beat heartbeat in Redis is less than 180 seconds old.
  - HTTP 503 with `"stale"` or `"unknown"` otherwise.
- **Heartbeat:** written every 60 s by `jobs.tasks.beat_heartbeat` on the worker (TTL 300 s).
- **What it proves:** that the worker and its scheduler are running and that web and worker share Redis.
- **What it does not check:**
  - the database (beyond Django being able to start),
  - agent-service,
  - any third-party API,
  - whether posts are actually publishing.
- **Not wired to anything.**
  - `railway.toml` sets no health-check path.
  - `render.yaml` sets one, but Render is not used.
  - If you add `/health/` as Railway's web health check, be aware that a stopped worker makes web deploys fail health checks. That may or may not be what you want.
- `/health/` is exempt from the HTTPS redirect, so plain-HTTP monitors work.

### 2.2 Application logs

- **Where they go:** stdout/stderr, collected by Railway. Open service → **Logs**, or run `railway logs --service web` / `--service worker`.
- **Levels** (`config/settings/production.py`):
  - `apps.*` at INFO,
  - Django and the root logger at WARNING,
  - `gunicorn.error` at INFO.
- **Retention** is whatever the Railway plan provides. Nothing is shipped elsewhere.
- **Useful log searches:**

| Search for | Meaning |
|---|---|
| `GATE BLOCK` | A post was stopped by a gate |
| `publish` / `PublishError` / `RateLimitError` | Provider failures |
| `LockNotAcquired` | Publish cycle overlapping (normal now and then; constant means stuck) |
| `deepseek` | AI generation failures |
| `sheets` / `invalid_grant` | Google Sheet sync failures |
| `emailer` | Approval email transport failures |
| `AgentClientError` / `agent-service` | agent-service unreachable |

### 2.3 Sentry (optional, off unless configured)

- `config/settings/base.py:396-405` initialises Sentry only when `SENTRY_DSN` is set, with 10% trace and profile sampling.
- **TO CONFIRM:** whether `SENTRY_DSN` is set on Railway, which Sentry organisation it belongs to, and who receives its alert emails.
- If it is not set, there is no error tracking at all.

### 2.4 In-app records you can check

| Where | What it shows |
|---|---|
| Publish → Sent (`templates/calendar/partials/publish_sent.html`) | Failed posts with the first 140 characters of the error |
| Social accounts / `/credentials/` account cards | Accounts in Error or Token-expiring state, with `last_error` |
| Analytics page banner "Reconnect for analytics" | An account whose analytics token lacks permission |
| Content board → review queue | Sheet rows that failed to parse |
| `/console/breakers`, `/console/healing`, `/console/brain` | Agent-service circuit breakers, healing incidents and fleet status (read from agent-service) |
| Django admin `/admin/` | Social accounts, credentials, notifications, approvals, CRM, outreach sends. **Posts, platform posts and `PublishLog` are not registered in admin**; use a Django shell to read them. |

`PublishLog` (`apps/publisher/models.py`) records every publish attempt with status code, a 1,000-character response body, the error and the duration. Its docstring says it is cleaned up after 90 days, but **no cleanup job exists**, so the table grows without limit.

### 2.5 In-app notifications and who they reach

The notification engine (`apps/notifications/engine.py`) delivers to the **in-app bell** and, depending on each user's preferences, to **email** (SMTP) or a **webhook**.

| Event | Sent by | Goes to |
|---|---|---|
| Post submitted, approved, changes requested, rejected | `apps/approvals/services.py` | The reviewer or author involved |
| Approval reminder / stalled approval | `apps/approvals/tasks.py` | Reviewer, then owner or manager. **The job is not scheduled, so this never fires.** |
| Inbox SLA overdue / new inbox message | `apps/inbox` | Assigned users. **The inbox poller is not scheduled; only webhooks deliver messages.** |
| Meeting prep, meeting capture, deck ready | `apps/joseph`, `apps/decks` | Joseph / the meeting owner (some via agent-service `/notifications`) |
| **Post published / post failed** | **nobody** | `POST_PUBLISHED` and `POST_FAILED` are defined but **never emitted** by the publisher. **A failed post alerts no one.** |
| **Social account disconnected** | **nobody** | Defined, never emitted by the health check |

- **Failed email or webhook deliveries** are attempted once. The retry function exists but is not scheduled.
- **The daily digest function** exists but is not scheduled.

### 2.6 Emails that go to a fixed person today

| Email | Recipient now | Where to change |
|---|---|---|
| Copy of every post published with one-click **Send** | `martin.maina@africacen.org` (default of workspace setting `review.copy_email`) unless a workspace overrode it | Workspace settings → `review.copy_email` |
| Railway deploy-failure and usage emails | The Railway account owner(s) (**TO CONFIRM**) | Railway → Account / Team settings |
| GitHub CI failure emails | The person who pushed, and watchers of `Martinxmaina/campaign-os` | GitHub notification settings |
| Sentry alerts (if configured) | **TO CONFIRM** | Sentry project → Alerts |
| Blotato, Ghost, DeepSeek, Resend and Google account notices (expiry, billing, quota) | Whoever owns each account (see [05-accounts-and-access.md](05-accounts-and-access.md)) | Each provider's dashboard |
| Agent-service breaker trips ("pause + page") | **TO CONFIRM.** That logic lives in agent-service, not in this repo. | agent-service config |

CI also has `.github/CODEOWNERS` set to `@JanSchm`, the **upstream BrightBean maintainer**. If the repo ever moves to an organisation with code-owner review enabled, review requests would go to that outside person. Change it.

## 3. What to set up after handover (recommended minimum)

In priority order. None of these needs code changes except items 4 and 5.

1. **Uptime monitor** on `https://<host>/health/` every 5 minutes, alerting the AfCEN on-call address. Any external monitor works (UptimeRobot, Better Stack, Railway's own checks). A 503 means publishing has stopped.
2. **A second uptime monitor** on the agent-service health route. If agent-service is down, nothing AI-generated can publish and outreach stops.
3. **Sentry.** Create a project in an AfCEN-owned Sentry organisation and set `SENTRY_DSN` on `web` and `worker`. Route alerts to a shared AfCEN mailbox, not a personal one.
4. **Emit failure notifications.** Add a `notify(... EventType.POST_FAILED ...)` call where `apps/publisher/engine.py` marks a post FAILED. Add the same for `SOCIAL_ACCOUNT_DISCONNECTED` in `apps/social_accounts/tasks.py`. Both event types and their default channels already exist.
5. **Schedule the dormant jobs** by adding entries to `jobs/schedules.py`:
   - approval reminders (hourly),
   - notification retry (every 5 minutes),
   - `PublishLog` pruning (needs a small task).

   Wrap the plain functions as Celery tasks first.
6. **Railway usage alerts.** Set spending and usage alerts in Railway's billing settings so a runaway cost or a suspended plan is caught.
7. **Provider expiry reminders.** Put calendar reminders against every token that expires on a known cycle:
   - direct LinkedIn about every 60 days,
   - Google OAuth refresh token if the consent screen is in "Testing" mode (7 days),
   - Ghost and Blotato keys if rotated.

## 4. Who should receive alerts

**TO CONFIRM** with AfCEN at handover. Fill in and keep this table current:

| Alert | Primary | Backup |
|---|---|---|
| Site or worker down (`/health/`) | | |
| agent-service down | | |
| Publish failures | | |
| Sentry errors | | |
| Railway billing | | |
| Provider token or billing expiry | | |
