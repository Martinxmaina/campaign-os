# Demo polish — Ghost analytics permanence + movable pipelines + Joseph Today charts

> Subagent-driven, TDD, one commit per task. Tests: `DJANGO_SETTINGS_MODULE=config.settings.test
> /Users/macbook/.local/bin/uv run pytest <paths> -q -p no:warnings`. CSP-safe (Alpine @click/hx-*,
> nonce on <script>; external CDN scripts only from jsdelivr — already allowed since Chart.js/flatpickr
> load from there). Don't run the whole suite per task.

**Goal:** Make the seeded demo fully testable: Ghost analytics permanent + auto-connected, both pipelines
movable (drag-drop → stage update) and showing the same canonical Django threads, and Joseph's home gains
charts + more context.

**Grounding:** Ghost analytics gap was `AnalyticsPlatformConfig.enabled_platforms()` excluding ghost (fixed
in prod manually; make permanent). Joseph pipeline reads `apps.crm.OutreachThread`; console pipeline
(`apps/intelligence/console_views.py::pipeline`) reads stale agent-service `/threads` — repoint it. Chart.js
4.4.6 loaded in base.html (analytics hero pattern ~line 1049). SortableJS via jsdelivr CDN for drag-drop.

---

### Task 1: Ghost analytics permanence + auto-connect from env
**Files:** Create `apps/social_accounts/management/commands/ensure_ghost_connected.py`, a data migration in
`apps/social_accounts/migrations/` (seed `AnalyticsPlatformConfig(platform="ghost", is_enabled=True)`);
Modify `docker-entrypoint.sh` (web role: run `ensure_ghost_connected` idempotently). Test:
`apps/social_accounts/tests/test_ensure_ghost.py`
- [ ] Failing tests: a data migration creates an enabled ghost `AnalyticsPlatformConfig` row; the
  `ensure_ghost_connected` command, when `GHOST_ADMIN_API_KEY` is set (env creds) and no ghost SocialAccount
  exists, creates a connected ghost SocialAccount (mock `get_provider(...).get_profile`); when one already
  exists or no env key → no-op (no duplicate, no crash).
- [ ] Run→fail.
- [ ] Implement: the data migration (idempotent `update_or_create`); the command (env-gated, idempotent,
  resolves creds from `settings.PLATFORM_CREDENTIALS_FROM_ENV['ghost']`, attaches to the org's oldest
  workspace like `apps/credentials/views.connect_ghost`); add `python manage.py ensure_ghost_connected || true`
  to the web role in docker-entrypoint.sh (after migrate).
- [ ] Run→pass. Commit `feat(analytics): enable ghost analytics by default + auto-connect from env key`.

### Task 2: Joseph pipeline drag-and-drop → stage update
**Files:** Modify `templates/joseph/pipeline.html`, `apps/crm/thread_views.py` (+ a `set_stage` view),
`apps/crm/urls.py` (or joseph urls); Test `apps/crm/tests/test_set_stage.py`
- [ ] Failing tests: POST `/crm/threads/<id>/stage/` with `stage=proposal_sent` updates the
  `OutreachThread.stage` + appends an `Activity(activity_type="stage_advanced")`; 403 for non-CRM roles;
  invalid stage → 400, no change.
- [ ] Run→fail.
- [ ] Implement: `set_stage` view (gated by `_can_manage_crm`/`_can_access_joseph`); validate against
  `OutreachThread.Stage`. In pipeline.html, load SortableJS (jsdelivr, nonce'd), make each stage column a
  Sortable list; on drop, `fetch`/`htmx` POST the thread id + target column's stage to `set_stage` (CSRF
  header). Keep cards as links (drag handle distinct from click).
- [ ] Run→pass. Commit `feat(joseph): drag-and-drop pipeline -> stage update (+ activity)`.

### Task 3: Console pipeline → Django threads + drag-and-drop
**Files:** Modify `apps/intelligence/console_views.py::pipeline` (read `apps.crm.OutreachThread`, group by
stage), `templates/console/pipeline.html` (stage columns + SortableJS → the same `set_stage` endpoint);
Test `apps/intelligence/tests/test_console_pipeline.py` (or nearest)
- [ ] Failing tests: `/console/pipeline` renders CRM `OutreachThread` rows grouped by stage columns (not
  agent-service traffic-light cols); drag-drop posts to `set_stage`; agent-service is NOT called.
- [ ] Run→fail.
- [ ] Implement: rewrite the console `pipeline` view to query CRM threads grouped by the same stage columns
  as Joseph's; template mirrors the Sortable wiring → `set_stage`. Remove the `safe_get('/threads')` call.
- [ ] Run→pass. Commit `feat(console): pipeline reads Django threads + drag-and-drop (parity with Joseph)`.

### Task 4: Joseph Today — charts + more context
**Files:** Modify `apps/joseph/views.py` (home context: chart data + week stats), `templates/joseph/
home_desktop.html` (+ `home_mobile.html` a compact chart); Test `apps/joseph/tests/test_home_charts.py`
- [ ] Failing tests: desktop home context includes `chart_by_track` (capital/threads per track),
  `chart_by_stage` (count per stage), `chart_quintile` (count per quintile) and `week_stats`
  (meetings_this_week, threads_advanced, replies, drafts) computed from CRM threads + activities +
  calendar; the template renders `<canvas>` elements + `json_script` data blocks; charts init script is
  nonce'd.
- [ ] Run→fail.
- [ ] Implement: compute the aggregates in the home view (CRM querysets + Activity counts + CalendarEvent
  this-week); add a "This week" context strip + three Chart.js canvases (bar: by-track, bar: by-stage,
  line/doughnut: quintile) fed via `{{ data|json_script:"..." }}` + a nonce'd init that mirrors the existing
  analytics-hero pattern in base.html.
- [ ] Run→pass. Commit `feat(joseph): Today charts (by-track/by-stage/quintile) + this-week context`.

---
## Self-review
Coverage: ghost permanence+auto-connect (T1), Joseph DnD (T2), console DnD+repoint (T3), Today charts (T4).
`set_stage` (T2) reused by T3. CSP: SortableJS from jsdelivr (already-allowed origin), nonce'd init.
Build order 1→4 (T2 defines set_stage used by T3). After: full Django suite; deploy dispatch web+worker
(+ run ensure_ghost_connected on boot). No agent-service change.
