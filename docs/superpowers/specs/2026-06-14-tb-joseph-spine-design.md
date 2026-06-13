# Design: TB Joseph Spine — principal surface + calendar feed + dossier render

**Date:** 2026-06-14
**Status:** Approved (UI mockups approved by Joseph/Martin) — ready for implementation plan
**Phase:** 2B (Joseph's Principal Intelligence Platform) — the spine that unifies TB.7 (surface),
TB.2 (dossier render), TB.0 (calendar/gmail feeds), wired to the existing Phase-1 intelligence plane.
**Repos:** waiis-dispatch-platform (Django, all UI + feeds) reading agent-service over HTTP.
**Build vehicle:** subagent-driven Workflow, task-by-task, TDD, commit per task.

## Problem

Joseph has a voice (TB.1) but no surface. He needs the single place he opens before every
conversation: mobile = one screen of signal (editorial), desktop = full operations. Everything is
built around a single seam — `JosephIntelligence` — so the external "knows-Joseph-end-to-end" AI
endpoint plugs in later with zero UI rework.

## Grounding (verified in code, 2026-06-14)

**agent-service (reuse as-is, no changes):**
- `GET /threads?traffic_light&owner&quintile` → `{items:[{id,subject,org,owner,stage,traffic_light,quintile,next_action}]}`
- `GET /threads/{id}` → `+ score, dossier_id, state{}`
- `GET /dossiers/{id}` → `{id,entity,body_md,sources:[{ref,trust}],red_flags:[],hooks:{track:text},status,thread_id}` (+ `updated_at` via TimestampMixin)
- `POST /threads/{id}/dossier` (lead) → triggers compile, `{dossier_id,sources}`
- `GET /knowledge/pages?q&entity_type&limit` → `{pages:[{slug,title,entity_type,status}]}`
- `GET /knowledge/pages/{slug}?tier=l0|l1|l2` → `{slug,title,tier,status,aliases,links,content}` (l0=abstract,l1=overview,l2=body)
- `GET /knowledge/pages/{slug}/revisions` → `{revisions:[{diff,source_refs,created_at}]}`
- `GET /notifications?unread` → `{items:[{id,kind,body,action{},urgent,read}]}`; `POST /notifications/{id}/read`
- `GET /content/items?sector&status` → `{items:[{id,title,sector,status,confidence,gate_verdict,variant_group}]}`
- `GET /news/digest?sector&africa` → news items (for Intelligence tab, org-filtered client-side)
- `POST /agents/herald/draft` accepts `voice_user="joseph"`, `channel` (already wired by TB.1)
- Auth: service JWT in `AGENT_SERVICE_TOKEN` already has role ≥ lead (verified against /voice). All
  reads above are member-gated → token works. No new agent-service routes for the spine.

**Django (reuse):**
- `apps/joseph/` exists (TB.1): `urls.py`, `views.py`, role gate `_can_manage_voice` (owner/admin/staff).
  Mounted at `/joseph/` (config/urls.py:52).
- `apps/common/agent_client.py`: `agent_get/agent_post/agent_put` + `AgentClientError`; `_safe_get` (agent-down → {}).
- `templates/console/base.html` extends `base.html`; Tailwind+Alpine+HTMX; CSP nonce `{{ request.csp_nonce }}`;
  HTMX CSRF wired in base.html. **Match this for desktop; mobile gets a lean own layout.**
- `apps/composer/models.py` Post: `review_assignee` (FK, related_name="review_queue"), `review_state`
  (ReviewState none/pending/approved/changes_requested/rejected).
- `apps/content_intake/models.py` ContentIntake: `owner`, `herald_content_id`, `post` (O2O).
- `apps/approvals/console_views.py` `ai_approvals`: Posts review_state=PENDING, owner-routed.
- `apps/members` RBAC: `request.org/workspace/workspace_membership.workspace_role`; role `PRINCIPAL` exists.
  `JOSEPH_APPROVER_EMAIL` setting defined (config/settings/base.py), currently unused.
- `jobs/schedules.py` BEAT_SCHEDULE dict — single source of truth.
- `apps/calendar/` is the internal CONTENT calendar only (PostingSlot/Queue). **No Google sync** → new model.
- Google OAuth today is Sheets-only (`GOOGLE_SHEETS_CLIENT_ID/SECRET/REFRESH_TOKEN`); `google-api-python-client` available.
- No service worker / PWA SW yet; manifest path `/static/favicon/site.webmanifest`; whitenoise serves static.

## Decisions (locked)

1. **One seam:** `apps/joseph/intelligence.py::JosephIntelligence` with `brief(thread_id, tier)`,
   `proposals()`, `ask(question)`. Today brief/proposals read agent-service; `ask()` returns a
   "not yet connected" stub (501-style dict). The future AI endpoint swaps the impl behind this class only.
2. **Role gate:** `_can_access_joseph(request)` = staff OR workspace_role in {owner, admin, principal}.
3. **Two surfaces, content-differentiated** (not resized): mobile editorial at `/joseph/`
   (device-detected or `?view=`), desktop operational at `/joseph/` too — one entry, responsive switch
   via a server-side `is_mobile` flag (UA hint) + a manual toggle; both share the same view data.
4. **L0 card maps onto the existing Dossier** (no agent-service change): WHO=thread.org+contact,
   WHY NOW=dossier.summary, HOOK=dossier.hooks[track], RED FLAGS=dossier.red_flags[:3],
   WARM PATH=dossier.meta.warm_path or "cold approach", FRESHNESS=updated_at + len(sources).
   L1=dossier.body_md; L2=linked wiki page (slug match on entity) tier l2, else body_md.
5. **Action queue = merge** of agent-service `/notifications?unread` (urgent first) + Django Posts
   review_state=PENDING (assigned to Joseph) + unlinked CalendarEvents (linkage suggestions).
   Each normalized to `ActionCard{kind,title,subtitle,actions[],href}`.
6. **Calendar/Gmail code ships now, data later.** New OAuth scopes (`calendar.readonly`,
   `gmail.readonly`) require Joseph's re-consent (a USER step). Until then, feeds no-op gracefully
   and the Today strip shows an empty state. Ship the updated `get_google_refresh_token.py`.
7. **Gate on personal content:** Joseph sees findings with suggested fixes + an audited override on
   his own posts (not a hard block). Override logged. (Lightweight in this spine; full per TB.6.)
8. **Deck / Sequence / Capture tabs are present but stubbed** ("coming in TB.4/TB.5") — the drawer
   shell is built so later phases drop in without re-layout.

## Architecture

### Adapter + readers (`apps/joseph/intelligence.py`, `apps/joseph/readers.py`)
- `readers.py`: thin typed wrappers over `agent_get` returning plain dicts/lists with graceful
  fallback: `list_threads(**filters)`, `get_thread(id)`, `get_dossier(id)`, `list_notifications(unread=True)`,
  `mark_read(id)`, `search_pages(q,entity_type)`, `get_page(slug,tier)`, `page_revisions(slug)`,
  `list_content(status)`, `news_about(org)`.
- `intelligence.py`: `JosephIntelligence` composing readers into `brief(thread_id,tier)->L0/L1/L2 dict`,
  `proposals()->[ActionCard]`, `ask(q)->{"connected":False,"message":...}`.

### Calendar/Gmail (`apps/joseph/models.py`, `integrations/google_calendar.py`, `integrations/gmail.py`, `apps/joseph/tasks.py`)
- `GoogleIntegration(user, refresh_token:Encrypted, scopes:JSON, last_synced_at)` (workspace-scoped).
- `CalendarEvent(workspace, google_event_id[unique], title, start, end, attendees:JSON, linked_thread_id:str|None, briefing_status, raw:JSON)`.
- `sync_google_calendar` (Celery 5min): build client from GoogleIntegration → upcoming events →
  fuzzy-match org/attendee to `list_threads()` org names (rapidfuzz/SequenceMatcher) → upsert;
  confident match auto-links + notifies, ambiguous → unlinked (surfaces as linkage suggestion).
- `sync_google_gmail` (Celery 10min): history.list → new messages → POST agent-service `/ingest`
  (X-Ingest-Key, source_type=email_inbound). Self-contained; no surface dependency.
- Both no-op (log + return) when no GoogleIntegration row → safe to deploy before consent.

### UI (Django views in `apps/joseph/views.py`, templates under `templates/joseph/`)
- `/joseph/` — home: mobile editorial (Today strip, Action queue, Red threads, Your content) OR
  desktop operational (funnel, escalations strip, action queue). One view, `is_mobile` switch.
- `/joseph/brief/<thread_id>/` — L0 card + L1/L2 toggle (HTMX swap) + Refresh (POST dossier compile).
- `/joseph/pipeline/` — traffic-light kanban by stage; thread cards; click → drawer.
- `/joseph/thread/<id>/` — drawer: Brief/Deck/Timeline/Intelligence/Tasks/Sequence tabs (HTMX),
  header actions (Request deck→stub, Capture→stub, Escalate→creates notification).
- `/joseph/knowledge/` — wiki search + entity_type filter; `/joseph/knowledge/<slug>/` detail w/ tier toggle + revisions.
- `/joseph/content/` — personal content queue (Posts for Joseph) + "Draft" (composer w/ voice_user=joseph).
- All gated by `_can_access_joseph`; agent-down → graceful empty states (reuse `_safe` pattern).

### PWA / offline (`static/js/joseph-sw.js`, manifest, register snippet)
- Service worker: app-shell cache + cache-first for visited `/joseph/brief/*` (L0 cards available offline).
- "I'm going in" button posts a precache hint (fetch + SW cache) for that brief.
- Registered only on `/joseph/*` pages (CSP-safe external script w/ nonce).

## Files

**Create:** `apps/joseph/intelligence.py`, `apps/joseph/readers.py`, `apps/joseph/models.py`,
`apps/joseph/tasks.py`, `apps/joseph/migrations/0001_*.py`, `integrations/__init__.py`,
`integrations/google_calendar.py`, `integrations/gmail.py`, `static/js/joseph-sw.js`,
templates: `joseph/_base.html`, `joseph/home_mobile.html`, `joseph/home_desktop.html`,
`joseph/brief.html`, `joseph/_l0_card.html`, `joseph/pipeline.html`, `joseph/thread_drawer.html`,
`joseph/_drawer_tabs/*.html`, `joseph/knowledge.html`, `joseph/knowledge_detail.html`,
`joseph/content_queue.html`. Tests under `apps/joseph/tests/`.

**Modify:** `apps/joseph/urls.py` (+routes), `apps/joseph/views.py` (+views, keep voice views),
`jobs/schedules.py` (+calendar 5min, +gmail 10min), `scripts/get_google_refresh_token.py`
(+calendar.readonly, gmail.readonly scopes), `templates/base.html` (sidebar Joseph link, role-gated;
bell poll), `config/settings/base.py` (Google calendar/gmail client id/secret if separate; reuse sheets client).

## Testing
- Adapter/readers: mocked `agent_get` → brief() maps dossier→L0 fields; proposals() merges sources;
  ask() returns not-connected.
- Views: each route 200 for Joseph, 403/redirect for non-Joseph; agent-down → renders empty state (no 500).
- Brief: L0 fields present; L1/L2 toggle returns the right content; Refresh posts compile.
- Pipeline/drawer: kanban groups by stage; drawer tabs each render; Escalate creates a notification.
- Calendar: fuzzy-match links an exact-org fixture event to the right thread; no-creds → task no-ops;
  ambiguous → unlinked suggestion appears in action queue.
- Gmail: history fixture → POST to /ingest called with source_type=email_inbound (mock).
- PWA: SW file served; `/joseph/` includes registration markup; manifest valid.
- Gate-on-personal: a flagged personal post shows findings + override path; override writes audit.

## Out of scope (later TB.*)
Full ATLAS orchestrator-worker dossier compile (TB.2 deep); voice-note meeting capture + Whisper
(TB.4); deck assembly + Google Slides (TB.5); proactive content proposals + Nexus "From Joseph's
desk" (TB.6); deal signals/data rooms (TB.8); the live AI `ask()` impl (the endpoint you'll share);
desktop calibration chart depth (render a basic version, deep calibration in TB.9).
