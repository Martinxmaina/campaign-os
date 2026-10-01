# 01 — System Overview

## 1. What Campaign OS is

Campaign OS is AfCEN's internal web application for planning, drafting, approving and publishing external communications. It also holds a fundraising CRM and a set of screens for the principal (Joseph).

It replaces four manual processes:
- planning content in a spreadsheet,
- drafting posts by hand,
- approving by email,
- tracking funder relationships in spreadsheets.

Users log in through a browser. There is no mobile app; the `/joseph/` area is a mobile-friendly web page that can be installed as a PWA.

**Origin of the code.** Campaign OS is a modified fork of **BrightBean Studio**, an open-source social media manager licensed under AGPL-3.0 (https://github.com/brightbeanxyz/brightbean-studio, forked at upstream commit `3d56b44` on 2026-06-08; see `docs/ADR-002-upstream-pin.md`). Much of the scheduling, calendar, media library, inbox and API code is inherited from BrightBean. The AfCEN-specific parts were added on top: content intake, the compliance gate, CRM, outreach, Joseph's surface, decks, AI Studio, and the Blotato and Ghost channels.

**The AGPL licence has an obligation attached.** Anyone who uses the running site must be able to get the complete source code of the version that is running. The `/about/` page links to `SOURCE_REPO_URL` (default `https://github.com/africacen/campaign-os`). That link must point at a repository that actually exists and is public, or AfCEN is out of compliance. See [04-known-gaps.md](04-known-gaps.md).

**The product has several names:**
- "Campaign OS" in the README and docs.
- "WAIIS Dispatch" in the page titles, `SITE_NAME` and `NOTICE`.
- `waiis-dispatch-platform` as the Python package name.
- "Brightbean" in some leftover config files.

They are all the same system.

## 2. Who uses it and for what

| User group | Main screens | What they do |
|---|---|---|
| Content team (Nduta, Dennis, Carren, Roberto per README) | Content board (`/console/intake/`), Compose, AI Studio, Calendar, Approvals, Analytics | Plan content, draft it (by hand or with AI), get it approved, schedule and publish it to social channels and the Ghost newsletter |
| Joseph (principal) | `/joseph/` | Read meeting briefs, see deal-flow, review his personal-voice content, record meeting notes |
| Resource-mobilisation team | `/crm/`, `/outreach/` | Track funders, contacts and relationship threads; send gated outreach email from their own Gmail |
| Admins | `/admin/`, `/credentials/`, Members, API Keys | Manage users, roles, channel connections and API keys |
| External tools / agents | `/api/v1/` (REST) and `/api/v1/mcp/` (MCP) | Create and schedule posts and read reports programmatically, authenticated with `cos_…` API keys |

Pillar-to-owner routing for new content is hard-coded in `apps/content_intake/owner_routing.py`:

| Pillar | Owner |
|---|---|
| energy | Dennis |
| agribusiness | Carren |
| ai | Joseph |
| digital | Nduta |
| minerals | Dennis |

## 3. Architecture

Campaign OS is **two separate services** that talk over HTTPS.

```
                         Users (browser)
                               │
                               ▼
┌──────────────────────── Campaign OS (THIS REPO) ────────────────────────┐
│  Railway service "web"    : Django 5.1 + gunicorn  (PROCESS_TYPE=web)    │
│  Railway service "worker" : Celery worker + embedded beat scheduler      │
│                             (PROCESS_TYPE=worker, runs `worker -B`)      │
│  Railway "Postgres"       : main database                                │
│  Railway "Redis"          : Celery broker (DB 1), cache + locks (DB 0)   │
└───────┬───────────────────────────┬──────────────────────────┬───────────┘
        │ HTTPS, bearer + HMAC      │ HTTPS, API keys / OAuth  │ HTTPS
        ▼                           ▼                          ▼
┌─ agent-service (NOT IN THIS REPO) ─┐   Blotato, Ghost, LinkedIn,   Google APIs
│ FastAPI + its own Postgres          │   X, Meta, YouTube, Threads   (Sheets, Gmail,
│ Compliance gate (Pass 1 + Pass 2)   │                                Calendar)
│ HERALD drafting, knowledge wiki,    │   DeepSeek (direct, for       Resend (email)
│ dossiers, voice profile, brain      │   AI Studio + campaign drafts)
│ Runs DeepSeek via Azure AI Foundry  │
└─────────────────────────────────────┘
```

- **Production URL (Campaign OS):** `https://web-production-2f84d.up.railway.app` (from repo docs; there is no custom domain).
- **Production URL (agent-service):** `https://web-production-e7cf9.up.railway.app` (from `docs/CURRENT_STATE.md` and `docs/platform-console-deploy.md`).
- Campaign OS never imports agent-service code. `tests/test_repo_isolation.py` enforces this. All integration is over HTTP.

### 3.1 The technology

| Layer | What is used |
|---|---|
| Language / framework | Python, Django 5.1, Django-Ninja (REST API), HTMX + Alpine.js + Tailwind CSS (UI) |
| Background jobs | Celery 5.4 with Redis; schedules in `jobs/schedules.py` only |
| Database | PostgreSQL (CI uses 16) |
| File storage | Local disk (`STORAGE_BACKEND=local`) or any S3-compatible bucket (`STORAGE_BACKEND=s3`). Which one production uses is **TO CONFIRM**. |
| Container | One Docker image (`Dockerfile`, Python 3.12-slim, Node 20 for the Tailwind build, ffmpeg for video). The role is chosen by the `PROCESS_TYPE` env var in `docker-entrypoint.sh`. |
| Hosting | Railway (`railway.toml`) |
| Dependencies | **Production installs from `requirements.txt` with pip**, not from `pyproject.toml`/`uv.lock`. A new library must be added to `requirements.txt` or it will not be deployed. |

### 3.2 Background schedule (all in `jobs/schedules.py`)

| Job | Frequency | What it does |
|---|---|---|
| `publish-cycle` | every 15 s | Finds due scheduled posts and publishes them (the publishing engine) |
| `blotato-reconcile` | every 60 s | Finishes Blotato posts that were still "publishing" when the inline wait ran out |
| `beat-heartbeat` | every 60 s | Writes a timestamp that `/health/` reads |
| `joseph-calendar-sync` | 5 min | Pulls Google Calendar events for connected users |
| `joseph-gmail-sync` | 10 min | Pulls recent inbound Gmail, triages replies, forwards to agent-service `/ingest` |
| `intake-sheets-sync` | 15 min | Pulls the content-planning Google Sheet into the Content board |
| `joseph-capture-prompts` | 15 min | Prompts for post-meeting capture |
| `joseph-meeting-prep` | 30 min | Pre-meeting brief cascade |
| `analytics-sync` | hourly | Pulls account and post metrics |
| `sweep-stale-idempotency` | hourly | Cleans API idempotency records |
| `sweep-stale-pending-activations` | hourly | Inherited BrightBean billing job; no-op here |
| `social-health-checks` | 6 h | Refreshes tokens and checks each connected account |
| `intelligence-reconcile` | 6 h | Inherited BrightBean billing job; no-op here |
| `calendar-gap-scan` | daily | Proposes dates for empty days in the next 14 days |
| `crm-score-threads` | daily | Recomputes CRM thread score / quintile / traffic light |
| `crm-no-reply` | daily | Flags threads amber after 14 days, red after 28 days without contact |
| `crm-sheet-mirror` | daily | Writes the CRM pipeline into a Google Sheet tab (only if `CRM_TRACKER_SHEET_ID` is set) |
| `outreach-advance` | daily | Sends due outreach sequence emails (through the gate) and opens tasks for manual steps |
| `outreach-no-reply` | daily | Opens follow-up tasks for unanswered outreach |
| `sweep-scheduled-org-deletions` | daily | Inherited BrightBean org-deletion job |

Several jobs exist in the code but are **not scheduled** and therefore never run. They are listed in [04-known-gaps.md](04-known-gaps.md).

## 4. How content flows through the system

### 4.1 From the planning sheet to a published post

1. **Intake.** Every 15 minutes, `intake-sheets-sync` reads the content-planning Google Sheet (ID in `CONTENT_INTAKE_SHEET_ID`, range `Sheet1!A:P` by default). Each row becomes or updates a `ContentIntake` item on the Content board.
   - Unknown sensitivity values become `private_hold`, and rows that fail to parse are quarantined in a review list. Rows are never silently dropped.
   - The sync only reads the sheet. It never writes back.
2. **Drafting.** An item can be drafted three ways:
   - by HERALD in agent-service (`POST /agents/herald/draft`),
   - by **AI Studio** (`/workspace/<id>/ai-studio/`) or the **campaign composer**, which call DeepSeek directly through `apps/common/deepseek_client.py`,
   - by hand in **Compose**.
3. **Review.** A post can be assigned for review.
   - The reviewer approves, requests changes, rejects, or uses **Send**, which approves, emails a copy and publishes in one click.
   - Reviewers can also act from an emailed link (`/review/<token>/`).
4. **Scheduling.** Every route to publishing ends the same way: each per-channel record (`PlatformPost`) is set to `scheduled` with a time.
5. **Publishing.** The `publish-cycle` job picks up due posts every 15 seconds. It runs the checks in step 6, then calls the channel's provider.
6. **The checks before every publish**, in `apps/publisher/engine.py::_dispatch_to_provider`:
   - **Intake gate:** blocks if the linked intake item is `private_hold` or `confidential`, has proof status `needs_verification`, or has any open unblock condition.
   - **Joseph gate:** if the intake item targets a Joseph-personal channel, an APPROVED approval action by Joseph must exist (`JOSEPH_APPROVER_EMAIL` or the item's owner email). Otherwise the post is parked as `pending_client`.
   - **Agent compliance gate:** the post must carry a `gate_id` that agent-service confirms as `pass`/`approved` (`GET /gate/verify/{id}`, HMAC-signed), and the text hash must match.
     - **Exception:** posts written by a person in Compose are marked `gate_bypassed=True` and skip this check. They still go through the intake gate and the Joseph gate.
7. **Result.**
   - Success: the post is marked `published` with its URL.
   - Failure: it is retried after 1 minute, then 5 minutes, then 30 minutes. After that it is marked `failed` and the error text appears in **Publish → Sent**.
   - Auth failure: the channel account is marked `error` and must be reconnected.

### 4.2 The compliance gate, accurately

The README says there is "no bypass route". **That is not what the code does.**
- Posts written by a person in Compose skip the agent-service compliance check (`apps/composer/views.py:94-96`, `apps/publisher/engine.py:326-329`). This is a deliberate design choice recorded in the code comments.
- Editing an already-published post through the platform-aware edit action (`apps/publisher/operations.py::edit_published_post`) re-publishes without any gate check.

AI-generated content, REST API posts and outreach emails do go through the gate.

### 4.3 CRM and outreach

- The CRM (`/crm/`) holds organisations (funders), contacts, outreach threads, activities and tasks. It is the master copy. An older copy in agent-service is no longer written (`docs/TABLE_OWNERSHIP.md`).
- Data can be imported from Excel, CSV or Google Sheets.
- Outreach (`/outreach/`) sends email from each owner's Gmail account. Every email goes through:
  - the gate (`POST /gate/check`),
  - a suppression list,
  - a daily cap and warm-up ramp,
  - an unsubscribe footer and `List-Unsubscribe` header.
- The public unsubscribe link is `/unsubscribe/<token>/`.

### 4.4 Joseph's surface

`/joseph/` shows meetings from his Google Calendar, briefs and dossiers (read from agent-service), the deal pipeline, knowledge-wiki pages, his content queue and his voice profile.

Several parts are **placeholders**. Voice-note transcription, meeting-note extraction, deck voice and section edits, and Google Slides output are all stubs (see [04-known-gaps.md](04-known-gaps.md)).

## 5. Everything Campaign OS connects to

| System | Used for | How it authenticates | Where the credential lives | Code |
|---|---|---|---|---|
| **agent-service** (AfCEN, separate FastAPI app) | Compliance gate, HERALD drafts, wiki, dossiers, voice profile, notifications, brain console | Bearer JWT (`AGENT_SERVICE_TOKEN`); HMAC-SHA256 with `STUDIO_SHARED_SECRET` for gate verify; `X-Ingest-Key` for `/ingest` | Railway env vars | `apps/common/agent_client.py`, `apps/publisher/gate_client.py`, `apps/publisher/ingest_webhook.py` |
| **Blotato** (`backend.blotato.com/v2`) | Publishing to Instagram, Facebook, Threads, Bluesky, LinkedIn (personal and page) and X; post analytics | `blotato-api-key` header | `BLOTATO_API_KEY` env var, or a "blotato" record in `/credentials/` | `providers/blotato.py`, `apps/social_accounts/blotato_client.py` |
| **Ghost** (`the-nexus-brief.ghost.io`) | Publishing the Nexus Brief as a blog post or newsletter email; post metrics; delete | Ghost Admin API key (`id:secret`), signed into a 5-minute JWT per request | `GHOST_ADMIN_API_KEY`, `GHOST_BASE_URL`, `GHOST_NEWSLETTER_SLUG` env vars, or `/credentials/` | `providers/ghost.py`, `providers/ghost_jwt.py` |
| **LinkedIn API** (direct) | Personal profile posting (proven live 2026-06); company page (blocked, no Community Management API approval) | OAuth 2.0 | `PLATFORM_LINKEDIN_*` env vars or `/credentials/`; user tokens encrypted in DB | `providers/linkedin*.py` |
| **X API** (direct) | Text posting only. Cannot be connected through the UI (no OAuth flow written). In practice X goes through Blotato. | Bearer | `PLATFORM_TWITTER_*` | `providers/twitter.py` |
| **Meta Graph / Instagram / Threads APIs** (direct) | Fully coded OAuth providers. Whether any direct Meta account is connected in production is **TO CONFIRM**; the recent work routes these channels through Blotato. | OAuth 2.0 | `PLATFORM_FACEBOOK_*`, `PLATFORM_INSTAGRAM_*` | `providers/facebook.py`, `instagram*.py`, `threads.py` |
| **YouTube Data / Analytics API** (direct) | Coded; usage in production **TO CONFIRM** | OAuth 2.0 | `PLATFORM_GOOGLE_*` | `providers/youtube.py` |
| **Google Sheets API** | Reading the content-planning sheet; writing the CRM tracker tab; CRM import | OAuth refresh token (or service-account JSON fallback) | `GOOGLE_SHEETS_CLIENT_ID/SECRET/REFRESH_TOKEN` | `apps/content_intake/sheets_sync.py`, `apps/crm/sheet_mirror.py` |
| **Gmail API** | Reading inbound mail (Joseph feeds, reply triage); sending outreach and approval emails | Per-user OAuth refresh token in `joseph.GoogleIntegration` (encrypted), using the same Google OAuth client as Sheets | DB + `GOOGLE_SHEETS_CLIENT_*` | `integrations/gmail.py` |
| **Google Calendar API** | Reading upcoming meetings | Same as Gmail | Same as Gmail | `integrations/google_calendar.py` |
| **Google Sign-In** | "Continue with Google" login | OAuth client | `GOOGLE_AUTH_CLIENT_ID/SECRET` | allauth |
| **DeepSeek** (`api.deepseek.com`, or Azure AI Foundry if configured) | AI Studio chat, campaign composer, caption drafts | API key | `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_API_VERSION`, `DEEPSEEK_MODEL` | `apps/common/deepseek_client.py` |
| **Resend** (`api.resend.com`) | Transactional email for approvals (first choice; falls back to Gmail, then SMTP) | API key | `RESEND_API_KEY`; from-address `DEFAULT_FROM_EMAIL` must be on a Resend-verified domain | `apps/approvals/emailer.py` |
| **SMTP server** | Other Django email (notifications, password reset, invites) | Username/password | `EMAIL_HOST*` env vars | Django |
| **S3-compatible storage** (if enabled) | Media library files | Access key | `S3_*` env vars | `config/settings/base.py` |
| **Sentry** (if enabled) | Error reporting | DSN | `SENTRY_DSN` | `config/settings/base.py` |
| **jsdelivr CDN** | Chart.js, flatpickr, SortableJS and Swagger UI loaded in the browser | none | — | `templates/base.html` |
| **Public RSS feeds** | "Feeds" reader in the composer | none | — | `apps/composer/curated_feeds.py` |

The agent-service has its own dependencies. They do not appear in this repo, and Campaign OS reaches them only through agent-service:
- Azure AI Foundry (DeepSeek-V4),
- self-hosted Firecrawl on Azure Container Apps (per `docs/phase2.md` §3.4),
- its own Postgres.

## 6. Current state (as of the last commit, 2026-07-03)

### 6.1 Working, according to code and repo docs

| Capability | Basis |
|---|---|
| Google Sheet → Content board sync every 15 min | `docs/CURRENT_STATE.md` (17 items synced on 2026-06-11); code verified |
| Compose, schedule, calendar, approvals, review-by-email, one-click Send | Code; recent commits (June–July 2026) |
| Publishing through Blotato (IG, FB, Threads, Bluesky, LinkedIn, X) | Code; commits `0fac45c`, `e371301`, `e5f43f9`, `d5633b9` show live testing |
| Publishing to Ghost (blog post or newsletter), with delete | Code; commits `9c24baa`, `0242c94` |
| Direct LinkedIn personal posting | `docs/CURRENT_STATE.md`: a live post went out 2026-06-11 |
| AI Studio and campaign composer (DeepSeek direct) | Commits `e24b4e3`, `68054cf`, `883dabc` (2026-07-02/03) |
| Analytics from Ghost and Blotato | Commits `5a515f8`, `f95e6fe`, `d5633b9` |
| CRM, import wizard, pipeline board, outreach engine | Code and tests |
| Reporting and Agent REST API, MCP endpoint | Code; `docs/api/` |
| Encrypted in-app credential store (`/credentials/`) | Code |

### 6.2 Not working or not live

| Capability | Why |
|---|---|
| Direct posting to the AfCEN LinkedIn **company page** | LinkedIn has not granted the Community Management API to AfCEN's developer app. See `docs/operations/linkedin-app-access-request.md`. Blotato's LinkedIn page target may work around this; that needs verifying (comment in `providers/blotato.py`). |
| LinkedIn personal analytics, first comments, auto-refresh | Same LinkedIn restriction. The OIDC token has no refresh, so the account has to reconnect when the token expires. |
| AI-approved posts sent with **Send** / **Approve & publish** | Blocked at publish with `GATE BLOCK: missing gate_id`. See [04-known-gaps.md](04-known-gaps.md) item G1. |
| Sheet write-back (updating the sheet's Status column) | Not built (`CONTENT_INTAKE_WRITEBACK_ENABLED` is read nowhere) |
| Inbox polling, approval reminders, notification retries, recurring posts, orphaned-media cleanup | Code exists but is not scheduled |
| Voice-note transcription, meeting extraction, deck voice/edit, Google Slides decks, `JosephIntelligence.ask` | Placeholders ("SEAM" comments) |
| Eval suites (`apps/evals`) | No way to run them except from tests |
| Instantly email transport | Stub that raises `NotImplementedError` |

### 6.3 What could not be checked from the repository

- Which channels are actually connected in production, and whether their tokens are still valid. The last code change was three months before this handover; LinkedIn OIDC tokens last about 60 days, and Blotato connections can expire.
- Whether the Railway services are still running and billed.
- Which production env vars are set (for example whether `SENTRY_DSN`, `RESEND_API_KEY`, `DEEPSEEK_API_KEY`, `STORAGE_BACKEND=s3` are configured).
- The state of the agent-service and where its source code is stored.

The first task for the new owner is the "Day 1 checks" in [02-runbook.md](02-runbook.md) §1.

## 7. Where things are in the code

| Path | Contents |
|---|---|
| `apps/publisher/engine.py` | The publishing engine and every pre-publish check. The most important file in the system. |
| `apps/publisher/gate_client.py` | Calls to the agent-service compliance gate |
| `apps/content_intake/` | Sheet sync, normalisation, Content board, HERALD bridge |
| `apps/composer/` | Posts, Compose, AI Studio (`chat_views.py`), campaign composer, AI generation (`generation.py`) |
| `apps/approvals/` | Review workflow, review-by-email, one-click Send, emailer |
| `apps/calendar/` | Calendar views, queues, posting slots |
| `apps/social_accounts/` | Connected channel accounts, OAuth callbacks, Blotato import, health checks |
| `apps/credentials/` | Encrypted per-platform app credentials (`/credentials/`) |
| `apps/analytics/` | Metrics sync and dashboards |
| `apps/crm/`, `apps/outreach/` | CRM and outreach email |
| `apps/joseph/`, `apps/decks/` | Principal surface and pitch decks |
| `apps/intelligence/console_views.py`, `config/console_urls.py` | The `/console/` screens (ideas, drafts, AI approvals, brain, breakers, news) |
| `apps/api/`, `apps/api_keys/`, `apps/mcp/` | REST API, API keys, MCP server |
| `apps/common/encryption.py` | Field encryption (AES-256-GCM, key derived from `SECRET_KEY` + `ENCRYPTION_KEY_SALT`) |
| `providers/` | One file per publishing platform |
| `integrations/` | Gmail and Google Calendar clients |
| `jobs/schedules.py` | Every background schedule |
| `config/settings/` | Settings (`base`, `development`, `production`, `test`) |
| `docker-entrypoint.sh` | What each Railway service runs at start |
| `scripts/get_google_refresh_token.py` | One-off tool to mint the Google refresh token |
| `docs/` | Design specs and plans from June–July 2026, API references, LinkedIn access guide |
