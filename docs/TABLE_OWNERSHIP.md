# Table ownership — the strangler split (Phase 2C)

> One owner per table (spec §3.2). This is the source-of-truth for "which service
> owns which data" as we strangle the FastAPI agent-service into Django. A row of
> data is written/migrated by exactly one service; the other reads it by id over
> HTTP (or not at all). Phase 2C makes Django the canonical CRM — the first
> strangler step.

## Django (`waiis-dispatch-platform`) — Django ORM + Django migrations

The canonical CRM lives in `apps/crm`. These tables are owned by Django; Django
runs their migrations and is the only writer.

| Table (model)              | App         | Owner   | Notes |
|----------------------------|-------------|---------|-------|
| `Organization`             | `apps/crm`  | Django  | Funders / DFIs / partners; tier + track_tags + wiki_slug. |
| `Contact`                  | `apps/crm`  | Django  | People at an Organization; seniority, warmth_source, consent_flags. |
| `OutreachThread`           | `apps/crm`  | Django  | The relationship/deal record; stage, score, quintile, traffic_light, owner. Holds `dossier_id` (an agent-service id) + `agent_thread_id` (migration source id). |
| `Activity`                 | `apps/crm`  | Django  | Per-thread timeline (email/call/meeting/note/stage_advanced); newest-first. |
| `Task`                     | `apps/crm`  | Django  | Per-owner / per-thread to-dos (send_email, follow_up, …). |
| `CrmImportJob`             | `apps/crm`  | Django  | Import-wizard job + mapping + per-row results (file / sheet). |

Scoring (DEAL-ENGINE weights) and the no-reply traffic-light sweep are **Django
Celery tasks** (`apps/crm/scoring.py`, `apps/crm/tasks.py`), scheduled in
`jobs/schedules.py`. They read/write the Django CRM tables above.

The rest of Campaign OS (posts, intake, publisher, approvals, members,
workspaces, credentials, …) is and remains Django-owned — see `CLAUDE.md`.

## agent-service (`agent-service`, FastAPI) — SQLAlchemy + Alembic migrations

The intelligence plane keeps its data; Django reads it **by id over HTTP**
(`apps/common/agent_client`), never by touching its DB.

| Data                       | Owner         | Notes |
|----------------------------|---------------|-------|
| Dossiers                   | agent-service | Compiled by ATLAS; `OutreachThread.dossier_id` points here. Compile now accepts the Django thread context (Task 9 seam); Django stores the returned id. |
| Wiki (entity pages)        | agent-service | LLM-native wiki (pg_trgm, Firecrawl monitors). |
| Gate (Pass-1 / Pass-2)     | agent-service | Compliance / semantic publish gate; `Task.gate_id` references a gate run. |
| Deliberation              | agent-service | Council / deliberation runs. |
| Voice profile              | agent-service | Versioned Joseph voice profile (`agent_name=voice:joseph`). |

## Rule

When adding a new table, pick **exactly one** owner and record it here. If both
services need the data, one owns it and the other reads it by id over the
`agent_client` seam — never a second writer, never a shared DB row.
