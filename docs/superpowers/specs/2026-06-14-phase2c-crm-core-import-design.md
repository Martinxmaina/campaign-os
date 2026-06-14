# Design: Phase 2C — CRM core + import (TC.0 + TC.1)

**Date:** 2026-06-14
**Status:** Approved — ready for implementation plan
**Phase:** 2C (Nduta's operational layer), first slice. **This is the first strangler step**: the CRM
becomes canonical in Django; agent-service is repointed to a stateless intelligence role for threads.
**Repos:** Django Campaign OS (waiis-dispatch-platform) = new owner of CRM data; agent-service =
intelligence (wiki/gate/dossier/deliberation) that operates on thread context Django sends.

## Problem

The team runs outreach from a spreadsheet. The CRM primitives are split — threads/dossiers/scoring/
sequences in agent-service, orgs/calendar/gmail in Django — and `Contact`, `Activity`, `Task` don't
exist anywhere. The spec's end-state is **one Django project**. This slice builds the canonical CRM in
Django (orgs, contacts, threads, activities, tasks) with full CRUD + an Excel/CSV/Sheet import wizard,
migrates the existing platform threads in, and flips the thread seam so Django owns the data.

## Grounding (verified in code, 2026-06-14)

**agent-service (FastAPI) — what exists today:**
- `app/db/models/ops.py`: `OutreachThread` (subject, state JSONB, contact_email/name, org, owner, stage,
  next_action, due_at, traffic_light, score, quintile, hubspot_id, last_touch_at, sector, track, pillar,
  dossier_id) and `Dossier` (entity, summary, body_md, sources, red_flags, hooks, status, thread_id).
- `app/services/scoring.py::score_engager(features, weights)` → (score, quintile, action, detail);
  `DEFAULT_WEIGHTS` = warmth .25 / seniority_org_fit .2 / pillar_fit .15 / engagement_recency .2 /
  engagement_frequency .1 / track_alignment .1. `app/services/routing_engagers.py::route_recent_engagers()`.
- `app/services/sequences.py` (start/advance/run_no_reply) — sequences live here (DEFERRED slice).
- `app/api/threads.py`: `GET /threads`, `GET /threads/{id}`, `POST /threads/{id}/dossier`, `GET /dossiers/{id}`.
- Dossier compile `app/services/dossier.py::build_dossier(session, entity, thread_id, ...)` reads the thread
  from its own DB + the wiki, runs DeepSeek (ATLAS).
- No `Organization`, `Contact`, `Activity`, `Task` models. Grant model is minimal.
- agent-service + Django are SEPARATE Postgres DBs → migration is API-driven, not a SQL copy.

**Django (Campaign OS) — what exists:**
- `apps/organizations/models.py::Organization` — bare (name, logo, timezone, billing); NO type/tier/track/
  website/linkedin/notes. (This is the workspace-owner org; the CRM "funder org" is a different concept —
  decision below.)
- `apps/joseph/readers.py` reads threads/dossiers over HTTP; `apps/joseph` pipeline + thread_drawer + brief
  render them. `apps/joseph/models.py` has `CalendarEvent` (linked_thread_id is a str).
- `apps/composer` has a CSV import (`CSVImportJob` + views) for POSTS — the UX pattern to reuse, not the data.
- `apps/inbox` = social inbox only (not email). `integrations/gmail.py` = inbound only (DEFERRED send).
- `jobs/schedules.py` = beat single source of truth. `apps/common/agent_client` = agent_get/post/put.

## Decisions (locked, from brainstorming)

1. **Canonical CRM in Django** (strangler step A). New app `apps/crm/`.
2. **First slice = TC.0 (models + CRUD UI) + TC.1 (import wizard).** Sequences, mailboxes/send, reply-triage,
   grants are LATER 2C slices.
3. **Data reality = both.** Migrate existing agent-service threads/dossiers AND build the import wizard for
   the team spreadsheet; dedup across the two (org name + contact email, fuzzy).
4. **Strangler split:** Django owns orgs/contacts/threads/activities/tasks **and** DEAL-ENGINE scoring +
   no-reply (ported as Django Celery tasks). agent-service keeps wiki/gate/**dossier compile**/deliberation/
   voice; its dossier-compile endpoint changes to accept **thread context from Django** instead of reading
   its own thread row. Dossier rows stay in agent-service; Django thread holds `dossier_id`.
5. **Repoint the Joseph surface** (pipeline/brief/thread-drawer) from HTTP `readers.list_threads/get_thread`
   to local Django querysets; dossier still fetched via `readers.get_dossier(dossier_id)`.
6. **CRM "funder org" is a NEW model** `crm.Organization` (distinct from the workspace-tenant
   `organizations.Organization`) to avoid overloading the tenant model. (Name it `crm.FunderOrg` if the
   import collides; default `crm.Organization` within the app namespace.)
7. Import accepts **.xlsx, .csv, and a Google Sheet URL** (Sheets client already wired).

## Architecture

### New app `apps/crm/` — models
- `Organization` (funder): name, type, track_tags[], tier, website, linkedin_url, wiki_slug, notes, timestamps.
- `Contact`: org FK, full_name, role, seniority, email, linkedin_url, phone, warmth_source, consent_flags
  JSON, last_verified, wiki_slug, timestamps.
- `OutreachThread`: org FK, primary_contact FK(null), track, owner FK(user), backstop FK(user,null), stage,
  warmth, score float, quintile int, next_action, next_action_due, traffic_light, dossier_id (str — agent
  -service UUID), data_room_url, restricted bool, last_touch, last_touch_channel, sector/track/pillar, timestamps.
- `Activity` (append-only): thread FK, activity_type, actor_type (human|agent), actor FK(user,null),
  agent_name(str,null), content_ref JSON, created_at.
- `Task`: thread FK(null), owner FK, type, status (open|completed|dismissed), due, drafted_content,
  gate_id(str,null), timestamps.
- Migration `0001_initial`. Register all in Django admin.

### Scoring + no-reply (ported to Django, `apps/crm/scoring.py` + `apps/crm/tasks.py`)
- Port `score_engager` (pure weighted fn) + weights (a `apps/crm` config constant or a `CrmConfig` row).
- `score_all_threads()` Celery beat (daily): compute score/quintile/traffic_light per thread.
- `flag_no_reply()` Celery beat (daily): amber >14d / red >28d since last_touch; set next_action.
- Parity test: Django scoring == agent-service `score_engager` on shared fixtures.

### Migration command `apps/crm/management/commands/import_threads_from_agent_service.py`
- Pull `GET /threads` (+ `/threads/{id}`, `/dossiers/{id}`) via `agent_client`.
- Create Organization/Contact/OutreachThread; carry dossier_id. Dedup against existing Django rows + a
  `--dry-run`. Idempotent (match on org name + contact email). Report created/updated/skipped counts.

### Import wizard `apps/crm/import_wizard.py` + `templates/crm/import/*` + `modules/`
- Model `CrmImportJob` (file ref or sheet_url, mapping JSON, status, row results JSON).
- 4 steps (HTMX, CSP-safe): **upload** (.xlsx/.csv via openpyxl/csv, or Google Sheet URL via the Sheets
  client) → **map** (sheet headers → CRM fields; remembered per workspace) → **preview+dedup** (new vs
  matched-existing; conflicts highlighted) → **commit** (create orgs/contacts/threads) → **error report**
  (per-row failures, downloadable; never silent drop). Row-hash idempotency.

### agent-service change (small, in agent-service repo)
- `POST /agents/dossier/compile` (or extend `POST /threads/{id}/dossier`) to accept a `thread_context`
  body `{entity, org, contact, track, ...}` and run ATLAS without reading a local thread row; return the
  dossier (stored in agent-service; id returned). Keep the old path working until Django cutover.

### UI (`modules/crm/` — Django views, BrightBean skin, extends base.html)
- **Organizations**: list (filter tier/track/type, search) + detail + create/edit forms.
- **Contacts**: list (filter org/seniority, search) + detail + create/edit.
- **Threads**: reuse the existing pipeline kanban + thread drawer (repointed to Django), plus team CRUD —
  edit stage/owner/next-action, **log activity**, **add task**; activity timeline + task list per thread.
- Import wizard entry in CRM nav. Role gate: workspace_role in {owner, admin, campaign_owner}.

### Ownership bookkeeping
- `docs/TABLE_OWNERSHIP.md`: orgs/contacts/threads/activities/tasks → Django (Django migrations);
  dossiers/wiki/gate/deliberation/voice → agent-service (Alembic). One owner per table (spec §3.2 rule).

## Testing
- Models: round-trip + FK integrity + admin registration.
- Import wizard: header mapping; dedup (new vs matched); commit creates rows; bad rows → error report,
  not silent; .xlsx + .csv + sheet-URL parsing; idempotent re-run.
- Migration command: pulls from a mocked agent_client; idempotent; dedups against imported rows; --dry-run.
- Scoring/no-reply: Django parity with agent-service fixtures; amber/red thresholds.
- Joseph surface repoint: pipeline/brief/thread-drawer render from Django; dossier fetched by id;
  agent-down → dossier empty-state, never 500.
- CRM UI: each view 200 for Nduta-role, 403 for others; CSP-safe.

## Out of scope (later 2C slices)
Sequences + no-reply *email send* (TC.3), connected mailboxes + deliverability (TC.2), reply-triage,
grant scanning/FORGE (TC.4), deliberation-gains-CRM-context (TC.5), self-healing (TC.6). Dossier compile
logic itself (stays in agent-service; only its input seam changes here). The full FastAPI decommission
(later strangler slices).
