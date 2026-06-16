<p align="center">
  <strong>Campaign OS</strong>
</p>

<p align="center">
  <strong>AfCEN's internal operating system for resource mobilisation — content, intelligence, deal-flow, and the principal's desk, with a compliance gate and a self-improving agent fleet.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue.svg" alt="License: AGPL-3.0"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.13%2B-blue.svg" alt="Python 3.13+"></a>
  <a href="https://www.djangoproject.com/"><img src="https://img.shields.io/badge/Django-5.1-green.svg" alt="Django 5.1"></a>
  <a href="https://docs.celeryq.dev/"><img src="https://img.shields.io/badge/Celery-5.4-brightgreen.svg" alt="Celery 5.4"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-agent--service-009688.svg" alt="FastAPI agent-service"></a>
</p>

---

## What is Campaign OS?

AfCEN is an African development & climate-infrastructure organisation that raises **philanthropic and bilateral grants**, **core operational funding**, **programme grants**, and **event sponsorship** (for WAIIS 2026). There is **no equity, no cap table, no token** — and several keywords are *existentially* banned from external communications because they would misrepresent AfCEN to funders like the AfDB, UNDP, Rockefeller, GEAPP, GIZ and Gates.

Campaign OS replaces spreadsheet tracking, manual drafting, email approval chains, and ad-hoc research with one platform that takes an idea or a funder relationship from raw signal → compliant, in-voice output → publication or send, while **AI agents draft, research, score, and learn from every human decision** — and a **two-pass compliance gate** stands between every word and the outside world.

It serves three audiences:

- **The content team** (Nduta, Dennis, Carren, Roberto) — plan, draft, gate, approve, schedule, publish across LinkedIn, X, Meta, YouTube, Threads, and Ghost.
- **The principal** (Joseph) — a mobile-first brief-before-every-meeting, capture-after, deal-flow oversight, and personal-voice content surface.
- **The agents** — HERALD, JARVIS, ATLAS, FORGE, DEAL-ENGINE, the Evaluator, and the Maintenance agent, governed by frozen constitutions, autonomy tiers, and three self-learning loops.

---

## Architecture — two planes, one gate

Campaign OS runs as **two cooperating services** (a strangler migration is consolidating them into the single Django project over time):

```
┌───────────────────────────── Campaign OS (Django) ─────────────────────────────┐
│  Surfaces:  content board · composer · calendar · CRM · outreach · /joseph/      │
│             · console (ideas/drafts/approvals/pipeline/learning/agents/brain)    │
│  Domains :  content_intake · composer · crm · outreach · joseph · approvals      │
│             publisher · analytics · social_accounts · credentials · notifications│
│  Jobs    :  Celery + Redis + beat (single schedule)                              │
│  THE GATE:  every external post / email / brief is verified before dispatch      │
└───────────────┬──────────────────────────────────────────────┬──────────────────┘
                │ HTTP (bearer/HMAC)                             │ first-party APIs
                ▼                                                ▼
┌──────── agent-service (FastAPI) — the intelligence plane ───┐   LinkedIn · X · Meta
│  Gate Pass 1 (rules) + Pass 2 (semantic)                    │   YouTube · Threads · Ghost
│  Knowledge wiki (L0/L1/L2, Karpathy-style, auditable)       │
│  Agents: HERALD · JARVIS · ATLAS · FORGE · DEAL-ENGINE      │
│  The brain: episodes · playbooks · eval suites · 3 loops    │
│  Azure AI Foundry → DeepSeek-V4                             │
└─────────────────────────────────────────────────────────────┘
```

**The compliance gate is the defining feature.** Two passes run on every external communication before it can be sent, published, or delivered — including content typed directly into the editor. There is no bypass route.

- **Pass 1** (deterministic, in-process): status-language without a signed source (`secured/committed/funded/…`), **hard-block** confidential keywords (these die at the gate, never route to a human), track-separation (WAIIS ⨯ AI 10Bn), unverified figures.
- **Pass 2** (semantic, agent): implied commitments, projections stated as fact, partner-separation nuance, untrue momentum claims.
- **Routing**: clean → publish per autonomy tier · flag → topic lead / Nduta / Joseph · block → dead, logged to audit.

---

## The self-learning agent brain

Each agent is five components — a **frozen constitution** (compliance + brand rules, changed only by human PR), a **versioned playbook** (the craft the system *learns*), scoped tools + wiki-first memory, an **eval suite**, and a self-correction loop. Three loops keep the fleet improving **and safe**:

| Loop | Cadence | What it does |
|---|---|---|
| **1 · in-run** | live | Circuit breakers (error rate, cost, gate-rejection) computed from episodes; trip → pause + page. |
| **2 · weekly reflection** | Fri | The **Evaluator** reads each agent's episodes→outcomes and proposes ≤3 playbook diffs — each backed by **≥3 evidence episodes** and gated by the agent's eval suite (a compliance-case failure auto-rejects). A human approves in the **diff-review console**; the new version hot-swaps; a **nightly rollback-watch** reverts any regression vs the 4-week baseline. |
| **3 · self-healing** | nightly | On a breaker trip the **Maintenance agent** queries traces for root cause → opens a healing incident with a *proposed* fix (config → reflection, code → PR). **No trace evidence → it stops** (no guessing). Never auto-applies, never commits to main. |

**Autonomy tiers (T0–T3)** are enforced in code, not prompts: an action class earns autonomy on a 4-week ≥90%-acceptance record and is demoted on incident. Money/commitment claims, named partners, political content, and Tier-1 funder comms are **permanently capped at T2**. The utility/rubrics are fixed Level-2 artifacts (the Gödel rule: agents never define "good" for themselves).

---

## Capabilities by domain

**Content pipeline**
- Google Sheets intake every 15 min — normalises sensitivity, parses multi-channel targets + unblock conditions, routes parse failures to review (never silently drops a row).
- HERALD drafts in per-house voice (AfCEN, WAIIS, AI 10Bn, Joseph) with an inline gate pre-check; JARVIS assembles the weekly Nexus Brief (Ghost).
- Sunday deliberation produces a ranked **ideas** rail with rationale chains; an accepted idea → HERALD draft → **AI Approvals** → calendar → publish.
- Per-platform character limits enforced (server + publish-time); calendar gap-scanner; configurable approval stages with owner-routing.

**Knowledge wiki** — an auditable, LLM-native wiki (`L0` 90-second brief / `L1` one-pager / `L2` deep) the agents read **before any web call**; revision history is the audit trail of what the agents know and when they learned it; two-source rule + contradiction escalation.

**CRM & outreach (the team's operational layer)** — canonical in Django: organizations, contacts, outreach threads (DEAL-ENGINE scored + quintiled + traffic-lit), append-only activities, tasks; an Excel/CSV/Google-Sheet **import wizard**; **drag-to-move pipeline** kanban; per-owner **Gmail send** with deliverability guardrails (daily cap + ramp + suppression + unsubscribe), gate-on-every-email, multi-step **sequences**, no-reply follow-ups, and inbound **reply-triage**.

**Joseph's principal surface (`/joseph/`)** — mobile editorial (one screen of signal, offline-capable PWA) + desktop operational: **L0/L1/L2 dossier briefs**, deal-flow pipeline + thread drawer, knowledge browser, personal-content queue, a responsive "Today" with by-track / by-stage / quintile charts, and his **voice profile** that HERALD applies + a weekly reflection refines.

**Analytics** — per-platform account + post insights (followers/subscribers, engagement) incl. Ghost subscriber analytics and LinkedIn company follower stats; capital funnel + multiplier; the Friday digest.

---

## Build status

| Phase | Scope | Status |
|---|---|---|
| **0** | FastAPI scaffold, gate Pass 1, ingest, agent harness | ✅ live |
| **1** | Knowledge wiki, gate Pass 2, HERALD/JARVIS, deliberation, fork rebrand, publishing, Nexus Brief, notifications | ✅ live |
| **2A** | Content intake + Sheets, composer, approvals, calendar, sensitivity | ✅ live |
| **2B** | Joseph voice profile + the principal surface (mobile + desktop), calendar/gmail feeds, dossier render | ✅ live |
| **2C** | CRM core + import · outreach engine (mailboxes, sequences, reply-triage) | ✅ live |
| **Brain** | Autonomy tiers + 3 learning loops + eval suites + diff-review + self-healing | ✅ live |
| **2B+** | Pre-meeting cascade · post-meeting voice capture · decks · data-room signals | ⏳ next |
| **2C+** | Grant scanning (FORGE) · deliberation-with-CRM-context | ⏳ planned |
| **3 / 4** | WAIIS summit · hardening | ⏳ planned |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Django 5.1 · Django-Ninja (Agent API) · HTMX + Alpine + Tailwind |
| Intelligence plane | FastAPI · SQLAlchemy + Alembic · Procrastinate |
| Queue / cache / locks | Celery 5.4 + Redis |
| Database | PostgreSQL + pgvector |
| AI | Azure AI Foundry → DeepSeek-V4 |
| Research | Firecrawl (self-hosted) |
| Email / docs | Gmail + Google Calendar/Sheets/Slides · Ghost Admin API |
| Storage | S3-compatible / Railway volume (media, voice notes, deck assets) |
| Observability | OpenTelemetry → Postgres span store |
| Deployment | Railway (Docker; role by `PROCESS_TYPE`) |

---

## Getting Started

### Prerequisites
Python 3.13+ · PostgreSQL 16+ (pgvector) · Redis 7+ · [`uv`](https://docs.astral.sh/uv/)

### Local setup (Campaign OS / this repo)
```bash
git clone https://github.com/Martinxmaina/campaign-os.git
cd campaign-os
uv sync
cp .env.example .env            # set DATABASE_URL, REDIS_URL, SECRET_KEY at minimum
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run gunicorn config.wsgi --bind 0.0.0.0:8000 &
uv run celery -A config worker -B --loglevel=info
```

Seed a realistic demo dataset (funders, contacts, threads, meetings, sequences) so every screen is walkable:
```bash
uv run python manage.py seed_demo --owner you@example.com   # --wipe to remove
```

### Tests
```bash
DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest -q     # Campaign OS: 1,380+ tests
# agent-service has its own suite (260+) under /agent-service
```

### Key environment variables
| Variable | Purpose |
|---|---|
| `DATABASE_URL` · `REDIS_URL` · `SECRET_KEY` | Core Django config |
| `ENCRYPTION_KEY_SALT` | Salt for encrypted credential/token fields |
| `AGENT_SERVICE_BASE_URL` · `AGENT_SERVICE_TOKEN` | Reach + authenticate to the intelligence plane (gate, wiki, brain, dossiers) |
| `AGENT_SERVICE_INGEST_URL` · `AGENT_SERVICE_INGEST_KEY` | Inbound ingest (email/webhooks → wiki/signal) |
| `GOOGLE_SHEETS_CLIENT_ID/SECRET/REFRESH_TOKEN` | Google OAuth (Sheets intake; Calendar/Gmail feeds with broader scopes) |
| `CONTENT_INTAKE_SHEET_ID` · `CONTENT_INTAKE_SHEET_RANGE` | The team's intake sheet |
| `GHOST_ADMIN_API_KEY` · `GHOST_BASE_URL` | Nexus Brief publish + subscriber analytics (Ghost) |
| `PLATFORM_LINKEDIN_*` / other `PLATFORM_*_CLIENT_*` | Per-platform OAuth app credentials |

> **Prod installs from `requirements.txt`** (not pyproject/uv.lock). Add any new runtime dep there too, or it won't ship.

Full reference: `.env.example`.

---

## Project Structure

```
apps/
  content_intake/  composer/  publisher/  approvals/   # content pipeline + gate chokepoint
  crm/             outreach/                            # Phase 2C: orgs/contacts/threads + email engine
  joseph/                                               # the principal surface (mobile + desktop, PWA)
  intelligence/                                         # console + agent-service HTTP client
  analytics/  social_accounts/  credentials/            # publishing, accounts, encrypted creds
  members/  organizations/  workspaces/  accounts/      # RBAC, tenancy, auth
  notifications/  inbox/  media_library/  evals/  api/   # supporting domains
integrations/      # google_calendar.py, gmail.py
jobs/schedules.py  # single source of truth for every Celery beat schedule
providers/         # linkedin / twitter / meta / youtube / threads / ghost / mock
config/settings/   # base / development / production / test

# agent-service/ (separate FastAPI service, deployed to Railway via `railway up`)
#   app/agents (constitutions + playbooks) · app/services (gate, evaluator, maintenance,
#   tiers, breakers, dossier, scoring) · app/api (gate, knowledge, threads, voice, brain) · app/jobs
```

Master plan + per-slice design specs & plans live under `docs/superpowers/`. Table ownership during the
strangler migration is tracked in `docs/TABLE_OWNERSHIP.md`.

---

## Deployment

Two Railway projects. **Campaign OS** (this repo) builds one Docker image; `PROCESS_TYPE` picks the role:

| `PROCESS_TYPE` | Runs |
|---|---|
| `web` | `migrate` → `gunicorn config.wsgi` (+ idempotent boot steps, e.g. `ensure_ghost_connected`) |
| `worker` | `celery -A config worker -B` (beat included) |

Services: `web`, `worker`, `postgres`, `redis`. The **agent-service** is a separate Railway project (FastAPI + its own Postgres) deployed via `railway up`. Deploy config: `railway.toml` + `Dockerfile`.

---

## Contributing

Campaign OS is an internal AfCEN tool; external contributions are not currently accepted. See `CONTRIBUTING.md` for the core-team workflow (brainstorm → spec → plan → subagent-driven build → review → deploy).

---

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE). Source attribution and upstream modification notices are in [NOTICE](NOTICE) and at [/about/](https://web-production-2f84d.up.railway.app/about/) per AGPL §5.
