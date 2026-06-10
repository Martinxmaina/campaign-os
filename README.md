<p align="center">
  <strong>Campaign OS</strong>
</p>

<p align="center">
  <strong>The content intelligence platform powering AfCEN's climate, energy & AI communications across Africa.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue.svg" alt="License: AGPL-3.0"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.13%2B-blue.svg" alt="Python 3.13+"></a>
  <a href="https://www.djangoproject.com/"><img src="https://img.shields.io/badge/Django-5.1-green.svg" alt="Django 5.1"></a>
  <a href="https://docs.celeryq.dev/"><img src="https://img.shields.io/badge/Celery-5.4-brightgreen.svg" alt="Celery 5.4"></a>
</p>

---

## What is Campaign OS?

Campaign OS is AfCEN's internal content operations platform — a single Django application that takes a raw content idea from intake all the way to multi-channel publication, with AI agents, editorial gates, and a learning loop built in.

It is used daily by the WAIIS, AfCEN, and AI 10Bn communications teams to plan, draft, gate, approve, schedule, and publish content across LinkedIn, X (Twitter), Meta, YouTube, and Threads.

---

## Core Capabilities

| Capability | What it does |
|---|---|
| **Content Intake** | Syncs the team's Google Sheet every 15 minutes — normalises sensitivity flags, parses multi-channel targets, extracts unblock conditions, routes parse failures to a human review queue. Never silently drops a row. |
| **Sensitivity Gate** | `private_hold` and `confidential` items cannot be scheduled or published until conditions are closed by their owner. Enforced at the publish-engine chokepoint — covers fresh dispatch, retry, and first-comment paths. |
| **Unblock Conditions** | Structured conditions (source verification, partner permission, legal milestone, figure confirmation) extracted from notes. Each blocks scheduling until a named owner closes it with an evidence note. |
| **HERALD / ATLAS agents** | AI drafting agents read the intake board as primary context. Submitted ideas get priority weighting in deliberation. Agents never see `private_hold` or `confidential` items. |
| **Multi-channel routing** | Nexus Brief pairing, gated-brief / lead-capture companions, Joseph-personal approval gate, article + cross-publish derivatives. |
| **Calendar gap scanner** | Daily beat scans a 14-day window per house and proposes slots for accepted, schedulable items respecting target publish dates and the 3-posts/week cadence. |
| **Approval workflow** | Configurable stages (none / optional / internal / internal + client). `campaign_owner` and `principal` roles can approve; `pillar_lead` approves within their pillar; `member` submits only. |
| **Publishing engine** | Direct first-party API integrations (LinkedIn, Meta, X, YouTube, Threads). Automatic retries, per-account rate-limit tracking, 90-day publish audit log. |
| **Eval framework** | `EvalCase` + `EvalRun` models with a dry-run runner. Compliance edge cases (sensitivity holds, unverified figures, partner permissions) are first-class eval cases, not afterthoughts. |
| **RBAC** | Five Campaign OS roles: `campaign_owner`, `principal`, `pillar_lead`, `member`, plus `admin`. Pillar-scoped for `pillar_lead`. Protected approval queues for Joseph and Kandeh as named approvers. |

---

## Architecture

```
Google Sheet ──► content_intake (15-min sync) ──► Intake Board
                        │
              normalization + conditions
                        │
                  HERALD / ATLAS ◄── agent_context (no private_hold)
                        │
                   composer (Post / PlatformPost)
                        │
              intake gate ──► publisher engine ──► LinkedIn / X / Meta / …
                        │
                   approvals → audit log
```

**Single Django project.** No microservices in the critical path. Agent intelligence (DeepSeek-V4 via Azure AI Foundry) is called over HMAC-signed HTTP from `apps/intelligence/`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Django 5.1, Django-Ninja (Agent API) |
| Queue | Celery 5.4 + Redis |
| Database | PostgreSQL 16 |
| Frontend | HTMX + Tailwind CSS |
| AI agents | Azure AI Foundry → DeepSeek-V4-Pro / Flash |
| Storage | S3-compatible (via django-storages) |
| Deployment | Railway (Docker, single image, role by `PROCESS_TYPE`) |

---

## Getting Started

### Prerequisites

- Python 3.13+
- PostgreSQL 16+
- Redis 7+

### Local setup

```bash
git clone https://github.com/Martinxmaina/campaign-os.git
cd campaign-os

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL, REDIS_URL, SECRET_KEY at minimum

# Migrate and create superuser
uv run python manage.py migrate
uv run python manage.py createsuperuser

# Start web + worker
uv run gunicorn config.wsgi --bind 0.0.0.0:8000 &
uv run celery -A config worker -B --loglevel=info
```

### Running tests

```bash
uv run pytest -x -q
# 797 tests, ~85 seconds
```

### Key environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis broker URL |
| `SECRET_KEY` | Django secret key |
| `CAMPAIGN_OS_ENCRYPTION_KEY` | Fernet key for encrypted credential fields |
| `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON` | Service account JSON (one line) for Sheets sync |
| `CONTENT_INTAKE_SHEET_ID` | Google Sheet ID for the team's content intake sheet |
| `CONTENT_INTAKE_SHEET_RANGE` | Sheet range, e.g. `Sheet1!A:P` |
| `AGENT_SERVICE_URL` | Base URL of the agent-service (intelligence plane) |
| `PLATFORM_HMAC_SECRET` | Shared HMAC secret with agent-service gate |
| `ENABLE_MOCK_PROVIDER` | `true` in dev to publish to mock instead of real platforms |

Full variable reference: `.env.example`

---

## Project Structure

```
apps/
  content_intake/   # Google Sheets sync, normalization, intake board, gate checks
  composer/         # Post, PlatformPost, Idea, Feed models; composer UI
  publisher/        # Dispatch engine, intake gate, provider adapters
  approvals/        # Approval workflow, threaded comments
  members/          # RBAC — campaign_owner/principal/pillar_lead/member roles
  evals/            # EvalCase + EvalRun for agent quality assurance
  intelligence/     # Azure AI Foundry client (HERALD/ATLAS/JARVIS)
  calendar/         # Content calendar view
  analytics/        # Platform analytics sync
  ...
jobs/
  schedules.py      # Single source of truth for all Celery beat schedules
providers/
  linkedin.py, twitter.py, meta.py, youtube.py, threads.py, mock.py
config/
  settings/         # base / dev / prod / test
  celery.py
```

---

## Deployment

Campaign OS is deployed on Railway as a single Docker image. The `PROCESS_TYPE` env var selects the role:

| `PROCESS_TYPE` | What runs |
|---|---|
| `web` | `migrate` → `gunicorn config.wsgi` |
| `worker` | `celery -A config worker -B` (includes beat) |

Railway services: `web`, `worker`, `postgres`, `redis`.

Deploy config: `railway.toml` + `Dockerfile`.

---

## Contributing

Campaign OS is an internal AfCEN tool. External contributions are not currently accepted. See `CONTRIBUTING.md` for the development workflow used by the core team.

---

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE).

Source attribution and upstream modification notices are in [NOTICE](NOTICE) and [/about/](https://web-production-2f84d.up.railway.app/about/) per AGPL §5.
