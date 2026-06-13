# TB Joseph Spine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use
> checkbox (`- [ ]`) syntax. TDD throughout. One commit per task. Run `uv run pytest -q` (Django,
> `DJANGO_SETTINGS_MODULE=config.settings.test`) — keep the suite green. CSP-safe templates only
> (no inline `onclick`/`onsubmit`; use Alpine `@click`, `hx-*`, and `{{ request.csp_nonce }}` on
> any `<script>`). Match `templates/console/base.html` styling for desktop; mobile uses a lean layout.

**Goal:** Build Joseph's principal surface (mobile editorial + desktop operational), the dossier
brief render, and the Google Calendar/Gmail feeds — all in `apps/joseph/`, reading agent-service
over HTTP through one `JosephIntelligence` seam, deployable now (calendar data lights up after a
user OAuth re-consent).

**Architecture:** Django views in `apps/joseph/` call `apps/joseph/readers.py` (thin `agent_get`
wrappers, graceful when agent-down) composed by `apps/joseph/intelligence.py::JosephIntelligence`.
New `apps/joseph/models.py` (GoogleIntegration, CalendarEvent) + `apps/joseph/tasks.py` (Celery
sync) + `integrations/` (Google clients). Spec: `docs/superpowers/specs/2026-06-14-tb-joseph-spine-design.md`.

**Tech Stack:** Django 5.1, HTMX, Alpine, Tailwind, Celery beat, google-api-python-client, httpx,
pytest-django. agent-service routes are fixed (see spec Grounding) — no agent-service changes.

---

### Task 1: Readers + JosephIntelligence adapter + role gate

**Files:**
- Create: `apps/joseph/readers.py`, `apps/joseph/intelligence.py`
- Modify: `apps/joseph/views.py` (add `_can_access_joseph`)
- Test: `apps/joseph/tests/test_intelligence.py`, `apps/joseph/tests/test_readers.py`

- [ ] **Step 1: Failing tests.** `readers.list_threads`/`get_dossier` call `agent_get` with the right
  path and return `[]`/`{}` on `AgentClientError`. `JosephIntelligence().brief(thread_id,"l0")` maps a
  fixture thread+dossier to `{who, why_now, hook, red_flags, warm_path, freshness}`; `proposals()`
  merges a fixture notification + a PENDING Post + an unlinked CalendarEvent into `ActionCard` dicts
  (`kind,title,subtitle,actions,href`); `ask("x")` returns `{"connected":False, ...}`. `_can_access_joseph`
  True for staff and workspace_role in {owner,admin,principal}, False otherwise.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `readers.py`: wrap `agent_get`/`agent_post` in try/except AgentClientError
  → safe defaults; paths per spec Grounding. `intelligence.py`: `L0` mapping = WHO `thread.org` +
  `thread.state.get("contact_name")`/role; WHY NOW `dossier.summary`; HOOK `dossier.hooks.get(thread.track)`
  or first hook; RED FLAGS `dossier.red_flags[:3]`; WARM PATH `dossier.meta.get("warm_path","cold approach")`;
  FRESHNESS `{updated_at, sources:len(dossier.sources)}`. `brief(tier)`: l1→`body_md`, l2→wiki page
  (slugify entity) tier l2 fallback body_md. `proposals()` merges three sources, urgent first. `ask()` stub.
  `_can_access_joseph(request)`: staff or `request.workspace_membership.workspace_role in {...}`.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): readers + JosephIntelligence adapter + role gate`.

### Task 2: Models (GoogleIntegration, CalendarEvent) + migration

**Files:**
- Create: `apps/joseph/models.py`, `apps/joseph/migrations/0001_initial.py` (via makemigrations)
- Test: `apps/joseph/tests/test_models.py`

- [ ] **Step 1: Failing test.** Create a `GoogleIntegration(user, refresh_token, scopes=["...calendar.readonly"])`
  and a `CalendarEvent(workspace, google_event_id="g1", title="Rockefeller sync", start=..., attendees=[...])`;
  assert round-trip, `google_event_id` unique, `linked_thread_id` nullable, `briefing_status` default "none".
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `GoogleIntegration`: FK user, `refresh_token=EncryptedTextField()`
  (from `apps.common.encryption`), `scopes=JSONField(default=list)`, `last_synced_at` null, timestamps.
  `CalendarEvent`: FK workspace, `google_event_id` unique indexed, title, start/end DateTime,
  `attendees=JSONField(default=list)`, `linked_thread_id=CharField(blank,default="")`,
  `briefing_status=CharField(default="none")`, `raw=JSONField(default=dict)`, timestamps.
  Run `makemigrations joseph`.
- [ ] **Step 4: Run, expect pass** + `migrate` clean.
- [ ] **Step 5: Commit** `feat(joseph): GoogleIntegration + CalendarEvent models`.

### Task 3: Mobile home (editorial surface) `/joseph/`

**Files:**
- Modify: `apps/joseph/urls.py`, `apps/joseph/views.py`
- Create: `templates/joseph/_base.html`, `templates/joseph/home_mobile.html`, `templates/joseph/home_desktop.html`
- Test: `apps/joseph/tests/test_home.py`

- [ ] **Step 1: Failing test.** GET `/joseph/` as Joseph (owner) → 200, contains "Action queue" and
  "Red threads"; as a viewer → 403/redirect; with agent down → 200 (empty states, no 500). `?view=mobile`
  renders the mobile template (bottom nav present), `?view=desktop` the desktop one.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `home(request)`: gate; `intel=JosephIntelligence()`; build context:
  `today_events` (CalendarEvent today for workspace, linked + unlinked), `actions=intel.proposals()`,
  `red_threads=readers.list_threads(traffic_light="red", owner="joseph")`, `content=Post.objects.filter(
  review_assignee=request.user)` (or owner). `is_mobile` from `?view=` or UA. Render mobile vs desktop
  template (desktop template may be minimal in this task; fleshed in Task 7). `_base.html` extends
  `base.html`, defines `{% block joseph %}` + (mobile) bottom nav Home/Pipeline/Brief. Mockup in spec.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): /joseph/ home (mobile editorial + desktop shell)`.

### Task 4: Brief card L0/L1/L2 `/joseph/brief/<thread_id>/`

**Files:**
- Modify: `apps/joseph/urls.py`, `apps/joseph/views.py`
- Create: `templates/joseph/brief.html`, `templates/joseph/_l0_card.html`
- Test: `apps/joseph/tests/test_brief.py`

- [ ] **Step 1: Failing test.** GET `/joseph/brief/<id>/` → 200, L0 card shows WHO/WHY NOW/HOOK/RED
  FLAGS/WARM PATH/FRESHNESS from a mocked thread+dossier. `?tier=l1` returns the dossier body_md (HTMX
  partial). POST `/joseph/brief/<id>/refresh/` calls `readers` compile (`POST /threads/{id}/dossier`) and
  redirects/swaps. Thread with no dossier → "No dossier yet — Compile" CTA.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `brief(request, thread_id)`: `intel.brief(thread_id, tier)`; render `_l0_card`
  for l0, body partial for l1/l2; HTMX `hx-get` tier toggle buttons. `brief_refresh` POST → readers compile
  → message + redirect. CSP-safe; tier buttons use `hx-get`+`hx-target`.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): L0/L1/L2 brief card + refresh`.

### Task 5: Pipeline kanban `/joseph/pipeline/`

**Files:**
- Modify: `apps/joseph/urls.py`, `apps/joseph/views.py`
- Create: `templates/joseph/pipeline.html`
- Test: `apps/joseph/tests/test_pipeline.py`

- [ ] **Step 1: Failing test.** GET `/joseph/pipeline/` → 200; threads grouped into stage columns;
  a card shows org, traffic-light dot, quintile, next_action; agent-down → empty columns, no 500.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `pipeline(request)`: `readers.list_threads()`; group by `stage` into ordered
  columns (`discover, qualify, proposal, diligence, committed` + catch-all); compute days-since-touch color
  from `last_touch_at`. Card links to `/joseph/thread/<id>/`. Desktop layout per spec mockup.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): pipeline traffic-light kanban`.

### Task 6: Thread drawer `/joseph/thread/<id>/` (tabs + actions)

**Files:**
- Modify: `apps/joseph/urls.py`, `apps/joseph/views.py`
- Create: `templates/joseph/thread_drawer.html`, `templates/joseph/_drawer_tabs/{brief,timeline,intelligence,tasks,deck,sequence}.html`
- Test: `apps/joseph/tests/test_thread_drawer.py`

- [ ] **Step 1: Failing test.** GET drawer → 200, header shows org+stage+score; tab params
  `?tab=brief|timeline|intelligence|tasks|deck|sequence` each return 200 (HTMX partials). Intelligence tab
  pulls the wiki page for the org + news_about(org). Deck/Sequence show "coming in TB.5/Phase 2C" stubs.
  POST `/joseph/thread/<id>/escalate/` creates a notification (mock readers.post) and returns ok.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `thread_drawer(request, thread_id)`: thread detail; tab dispatch renders the
  matching partial. Brief tab reuses `_l0_card`. Timeline from `thread.state`/available activity.
  Intelligence: `readers.search_pages`/`get_page` by org slug + `readers.news_about(org)`. Header actions
  (Request deck/Capture → stubs; Escalate → `readers` create notification). CSP-safe tabs via `hx-get`.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): thread drawer (tabs + escalate)`.

### Task 7: Desktop home (funnel + escalations + action queue)

**Files:**
- Modify: `apps/joseph/views.py`, `templates/joseph/home_desktop.html`
- Test: `apps/joseph/tests/test_home_desktop.py`

- [ ] **Step 1: Failing test.** Desktop home renders a capital-funnel summary (draft/scheduled/published
  counts from `readers.list_content`), an escalations strip (urgent notifications), and the action queue.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** Compute funnel counts from `readers.list_content(status=...)`; escalations =
  `[a for a in proposals() if a.urgent]`. Flesh `home_desktop.html` per spec mockup (nav row matching console).
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): desktop home (funnel + escalations + action queue)`.

### Task 8: Knowledge browser `/joseph/knowledge/` + detail

**Files:**
- Modify: `apps/joseph/urls.py`, `apps/joseph/views.py`
- Create: `templates/joseph/knowledge.html`, `templates/joseph/knowledge_detail.html`
- Test: `apps/joseph/tests/test_knowledge.py`

- [ ] **Step 1: Failing test.** GET `/joseph/knowledge/?q=rock&entity_type=funder` → 200 lists pages;
  GET `/joseph/knowledge/<slug>/` → 200 shows title + L1 content; `?tier=l2` swaps to body; revisions listed.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `knowledge(request)`: `readers.search_pages(q, entity_type)`; filter chips for
  entity_type (funder/org/person/initiative/topic). `knowledge_detail(request, slug)`: `readers.get_page(slug,tier)`
  + `readers.page_revisions(slug)`; tier toggle (HTMX); render `links` as in-app links.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): knowledge browser + page detail`.

### Task 9: Personal content queue `/joseph/content/` + voice draft

**Files:**
- Modify: `apps/joseph/urls.py`, `apps/joseph/views.py`
- Create: `templates/joseph/content_queue.html`
- Test: `apps/joseph/tests/test_content_queue.py`

- [ ] **Step 1: Failing test.** GET `/joseph/content/` → 200, lists Posts where `review_assignee`/author is
  Joseph sorted by publish date; a flagged post shows gate findings + an "Override (logged)" action;
  override POST writes an audit record + sets review_state. "Draft" action links to composer with voice.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `content_queue(request)`: Posts for Joseph; surface gate findings if present
  on the post; override view sets state + logs (reuse existing audit/ApprovalAction if available, else a
  simple log). "Draft new" → composer URL (existing) carrying intent to call HERALD with `voice_user=joseph`.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): personal content queue + audited gate override`.

### Task 10: Google Calendar feed (client + sync task + beat + fuzzy link)

**Files:**
- Create: `integrations/__init__.py`, `integrations/google_calendar.py`, `apps/joseph/tasks.py`
- Modify: `jobs/schedules.py`, `scripts/get_google_refresh_token.py`
- Test: `apps/joseph/tests/test_calendar_sync.py`

- [ ] **Step 1: Failing test.** With a mocked Google client returning an event titled "Rockefeller
  strategy" and a thread org "Rockefeller Foundation", `sync_google_calendar()` upserts a CalendarEvent and
  auto-links it (confidence>0.9) to that thread; an ambiguous title stays unlinked. No GoogleIntegration →
  task returns `{"skipped":"no-credentials"}` (no exception).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `google_calendar.py`: `build_calendar_service(integration)` via
  `google.oauth2.credentials.Credentials(refresh_token=...)` + `googleapiclient.discovery.build`;
  `upcoming_events(service, days=14)`. `tasks.sync_google_calendar` (`@shared_task`): for each
  GoogleIntegration → events → fuzzy-match (difflib.SequenceMatcher ratio, threshold 0.9 auto, 0.6–0.9
  suggestion) against `readers.list_threads()` org names → upsert CalendarEvent + set linked_thread_id +
  notify on auto-link. Register beat `joseph-calendar-sync` every 300s. Add `calendar.readonly` +
  `gmail.readonly` scopes to the OAuth script.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): Google Calendar feed + fuzzy thread linkage`.

### Task 11: Gmail feed (history sync → agent-service ingest)

**Files:**
- Create: `integrations/gmail.py`
- Modify: `apps/joseph/tasks.py`, `jobs/schedules.py`
- Test: `apps/joseph/tests/test_gmail_sync.py`

- [ ] **Step 1: Failing test.** Mocked Gmail client returns 2 new messages; `sync_google_gmail()` POSTs
  each to agent-service `/ingest` with `source_type="email_inbound"` (mock `httpx`/ingest call) using the
  ingest key; no GoogleIntegration → `{"skipped":"no-credentials"}`.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `gmail.py`: `build_gmail_service(integration)`; `recent_messages(service,
  history_id|since)`. `tasks.sync_google_gmail`: fetch → for each, POST to
  `settings.AGENT_SERVICE_INGEST_URL` with header `X-Ingest-Key: settings.AGENT_SERVICE_INGEST_KEY`,
  body `{source_type:"email_inbound", payload:{...}}`. Register beat `joseph-gmail-sync` every 600s.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): Gmail inbound sync → agent-service ingest`.

### Task 12: PWA / service worker + nav + bell

**Files:**
- Create: `static/js/joseph-sw.js`, `static/joseph/manifest.json` (or reuse site.webmanifest)
- Modify: `templates/joseph/_base.html` (SW register, bell poll), `templates/base.html` (sidebar Joseph link, role-gated)
- Test: `apps/joseph/tests/test_pwa.py`

- [ ] **Step 1: Failing test.** `/joseph/` HTML includes the SW registration script (with csp_nonce) and a
  manifest link; the SW JS file is served (200) from static. Sidebar shows a "Joseph" link only for
  Joseph-capable users.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `joseph-sw.js`: install caches app shell; fetch handler cache-first for
  `/joseph/brief/` GETs + network-first elsewhere. Register in `_base.html` via
  `<script nonce="{{ request.csp_nonce }}">navigator.serviceWorker.register('/static/js/joseph-sw.js',{scope:'/joseph/'})</script>`.
  Bell: Alpine component polling `readers`-backed `/joseph/notifications.json` (add a small JSON view) every
  30s. Sidebar link in base.html gated by `_can_access_joseph` (expose via context processor or template check).
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(joseph): PWA service worker + sidebar nav + notification bell`.

---

## Self-review notes
- Every task is independently testable and commits separately; UI tasks (3–9, 12) depend on Task 1
  (adapter) and Task 2 (models, used by home/calendar). Build order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 →
  9 → 10 → 11 → 12 (sequential; they share urls.py/views.py/base.html so avoid parallel file edits).
- No agent-service changes — all reads use existing member-gated routes with the existing service token.
- Calendar/Gmail ship behind a no-credentials no-op so the deploy is safe before Joseph's OAuth re-consent.
- After all tasks: run full Django suite; deploy dispatch web+worker via `railway up` (agent-service untouched).
