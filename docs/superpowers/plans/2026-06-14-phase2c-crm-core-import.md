# Phase 2C — CRM core + import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use
> checkbox (`- [ ]`) syntax. TDD throughout, one commit per task. Tests:
> `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <paths> -q -p no:warnings`.
> Do NOT run the whole suite per task (slow) — the orchestrator runs it at the end. CSP-safe templates only
> (no inline onclick/onsubmit; Alpine `@click` + `hx-*`; `nonce="{{ request.csp_nonce }}"` on `<script>`);
> desktop templates `{% extends "base.html" %}` (BrightBean skin). **requirements.txt gotcha:** the prod
> Docker image installs from `requirements.txt`, NOT pyproject/uv.lock — any new runtime dep (openpyxl)
> MUST be added to `requirements.txt` or it won't ship.

**Goal:** Build the canonical CRM in Django (`apps/crm`: Organization, Contact, OutreachThread, Activity,
Task) with CRUD UI + a 4-step import wizard, migrate existing agent-service threads in, port DEAL-ENGINE
scoring + no-reply to Django, flip the dossier-compile seam, and repoint the Joseph surface to Django.

**Architecture:** New `apps/crm` owns CRM data (Django = canonical — the first strangler step). Scoring +
no-reply become Django Celery tasks. agent-service keeps wiki/gate/dossier-compile/deliberation; its
dossier-compile endpoint takes thread context from Django. The Joseph pipeline/brief/thread-drawer read
Django querysets locally; dossiers still fetched from agent-service by id.

**Tech Stack:** Django 5.1, HTMX, Alpine, Tailwind, Celery beat, openpyxl (xlsx), httpx (agent_client),
google sheets client (existing), pytest-django. Spec: `docs/superpowers/specs/2026-06-14-phase2c-crm-core-import-design.md`.

---

### Task 1: `apps/crm` scaffold + the five models + admin

**Files:**
- Create: `apps/crm/__init__.py`, `apps/crm/apps.py`, `apps/crm/models.py`, `apps/crm/admin.py`,
  `apps/crm/migrations/__init__.py`
- Modify: `config/settings/base.py` (add `"apps.crm"` to LOCAL_APPS)
- Test: `apps/crm/tests/__init__.py`, `apps/crm/tests/test_models.py`

- [ ] **Step 1: Failing tests.** Create an `Organization(name="Rockefeller", type="funder", tier="tier1_anchor",
  track_tags=["ai10bn"])`; a `Contact(org=org, full_name="Dr. Okonkwo", seniority="vp", email="x@y.org")`;
  an `OutreachThread(org=org, primary_contact=contact, owner=user, stage="engaged", track="ai10bn")`; an
  `Activity(thread=thread, activity_type="note", actor_type="human", actor=user)`; a `Task(thread=thread,
  owner=user, type="send_email", status="open")`. Assert round-trip + that `Activity` is ordered newest-first
  and `OutreachThread.org` / `.primary_contact` FKs resolve.
- [ ] **Step 2: Run, expect fail** (app/models don't exist).
- [ ] **Step 3: Implement.** `apps.py` `CrmConfig(name="apps.crm")`. `models.py`:
  ```python
  import uuid
  from django.conf import settings
  from django.db import models

  class TimestampedUUID(models.Model):
      id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
      created_at = models.DateTimeField(auto_now_add=True)
      updated_at = models.DateTimeField(auto_now=True)
      class Meta: abstract = True

  class Organization(TimestampedUUID):
      class Type(models.TextChoices):
          FUNDER="funder"; BILATERAL="bilateral"; DFI="dfi"; CORPORATE="corporate"; PARTNER="partner"; GOVERNMENT="government"
      class Tier(models.TextChoices):
          T1="tier1_anchor","Tier 1 / Anchor"; T2="tier2_warm","Tier 2 / Warm"; T3="tier3_cold","Tier 3 / Cold"
      name = models.CharField(max_length=255, db_index=True)
      type = models.CharField(max_length=20, choices=Type.choices, default=Type.FUNDER)
      track_tags = models.JSONField(default=list, blank=True)   # ["core","ai10bn","waiis","programs"]
      tier = models.CharField(max_length=16, choices=Tier.choices, blank=True, default="")
      website = models.URLField(blank=True, default="")
      linkedin_url = models.URLField(blank=True, default="")
      wiki_slug = models.CharField(max_length=160, blank=True, default="")
      notes = models.TextField(blank=True, default="")
      def __str__(self): return self.name

  class Contact(TimestampedUUID):
      class Seniority(models.TextChoices):
          C="c_suite","C-suite"; VP="vp"; DIR="director"; MGR="manager"; AN="analyst"
      org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="contacts")
      full_name = models.CharField(max_length=255, db_index=True)
      role = models.CharField(max_length=255, blank=True, default="")
      seniority = models.CharField(max_length=16, choices=Seniority.choices, blank=True, default="")
      email = models.EmailField(blank=True, default="", db_index=True)
      linkedin_url = models.URLField(blank=True, default="")
      phone = models.CharField(max_length=40, blank=True, default="")
      warmth_source = models.CharField(max_length=32, blank=True, default="")  # direct_relationship|warm_intro|conference|cold
      consent_flags = models.JSONField(default=dict, blank=True)
      last_verified = models.DateField(null=True, blank=True)
      wiki_slug = models.CharField(max_length=160, blank=True, default="")
      def __str__(self): return self.full_name

  class OutreachThread(TimestampedUUID):
      class Stage(models.TextChoices):
          TARGETED="targeted"; ENGAGED="engaged"; PROPOSAL="proposal_sent"; DISCUSSION="in_discussion"
          COMMITTED="committed"; CONTRACTED="contracted"; CLOSED="closed"
      org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="threads")
      primary_contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name="threads")
      track = models.CharField(max_length=32, blank=True, default="")
      owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="owned_threads")
      backstop = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="backstop_threads")
      stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.TARGETED)
      warmth = models.CharField(max_length=8, blank=True, default="")   # cold|warm|hot
      score = models.FloatField(default=0.0)
      quintile = models.IntegerField(default=0)
      next_action = models.TextField(blank=True, default="")
      next_action_due = models.DateField(null=True, blank=True)
      traffic_light = models.CharField(max_length=8, default="green")   # green|amber|red
      dossier_id = models.CharField(max_length=64, blank=True, default="")  # agent-service Dossier UUID
      data_room_url = models.URLField(blank=True, default="")
      restricted = models.BooleanField(default=False)
      sector = models.CharField(max_length=32, blank=True, default="")
      pillar = models.CharField(max_length=48, blank=True, default="")
      last_touch = models.DateTimeField(null=True, blank=True)
      last_touch_channel = models.CharField(max_length=32, blank=True, default="")
      agent_thread_id = models.CharField(max_length=64, blank=True, default="", db_index=True)  # source id from migration
      def __str__(self): return f"{self.org.name} · {self.stage}"

  class Activity(TimestampedUUID):
      thread = models.ForeignKey(OutreachThread, on_delete=models.CASCADE, related_name="activities")
      activity_type = models.CharField(max_length=32)   # email_sent|email_reply|call|meeting|note|stage_advanced|...
      actor_type = models.CharField(max_length=8, default="human")  # human|agent
      actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
      agent_name = models.CharField(max_length=48, blank=True, default="")
      content_ref = models.JSONField(default=dict, blank=True)
      class Meta: ordering = ["-created_at"]

  class Task(TimestampedUUID):
      class Status(models.TextChoices):
          OPEN="open"; DONE="completed"; DISMISSED="dismissed"
      thread = models.ForeignKey(OutreachThread, on_delete=models.CASCADE, null=True, blank=True, related_name="tasks")
      owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crm_tasks")
      type = models.CharField(max_length=32)
      status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
      due = models.DateField(null=True, blank=True)
      drafted_content = models.TextField(blank=True, default="")
      gate_id = models.CharField(max_length=64, blank=True, default="")
  ```
  `admin.py`: register all five with sensible `list_display`. Add `"apps.crm"` to LOCAL_APPS. Run
  `makemigrations crm`.
- [ ] **Step 4: Run, expect pass** + `migrate` clean.
- [ ] **Step 5: Commit** `feat(crm): apps/crm scaffold + Organization/Contact/OutreachThread/Activity/Task models`.

### Task 2: Port DEAL-ENGINE scoring to Django

**Files:** Create `apps/crm/scoring.py`; Test `apps/crm/tests/test_scoring.py`

- [ ] **Step 1: Failing test.** `score_thread_features(features)` returns `(score, quintile, action)` matching
  the agent-service `score_engager` weights on a shared fixture: features
  `{warmth:1.0, seniority_org_fit:0.8, pillar_fit:0.5, engagement_recency:0.6, engagement_frequency:0.2,
  track_alignment:1.0}` → assert score ≈ 0.25+0.16+0.075+0.12+0.02+0.10 = 0.725, quintile 4
  (`int(0.725*5)+1`). Edge: empty features → score 0.0, quintile 1.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** (port from `agent-service/app/services/scoring.py`):
  ```python
  WEIGHTS = {"warmth":0.25,"seniority_org_fit":0.20,"pillar_fit":0.15,
             "engagement_recency":0.20,"engagement_frequency":0.10,"track_alignment":0.10}

  def score_thread_features(features: dict) -> tuple[float, int, str]:
      score = round(sum(WEIGHTS[k] * float(features.get(k, 0.0)) for k in WEIGHTS), 4)
      quintile = max(1, min(5, int(score * 5) + 1))
      action = "advance" if quintile >= 4 else "nurture" if quintile >= 2 else "deprioritize"
      return score, quintile, action
  ```
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(crm): port DEAL-ENGINE weighted scoring to Django`.

### Task 3: Scoring + no-reply Celery tasks + beat

**Files:** Create `apps/crm/tasks.py`; Modify `jobs/schedules.py`; Test `apps/crm/tests/test_tasks.py`

- [ ] **Step 1: Failing tests.** `flag_no_reply()` sets `traffic_light="amber"` on a thread with
  `last_touch` 15 days ago and `"red"` at 29 days ago, leaves a 3-day-old thread green; `score_all_threads()`
  writes `score`/`quintile`/`traffic_light` derived from features assembled from the thread
  (warmth/seniority/recency). Both registered in `settings.CELERY_BEAT_SCHEDULE`.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `@shared_task` `flag_no_reply` (uses `django.utils.timezone.now()`, thresholds
  14/28 days on `last_touch`, skips closed stages); `@shared_task` `score_all_threads` (build a features dict
  from each thread — map warmth/seniority/last_touch-recency → 0..1 — call `score_thread_features`, persist).
  Register in `jobs/schedules.py`: `"crm-score-threads"` (daily) + `"crm-no-reply"` (daily).
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(crm): daily score + no-reply Celery tasks`.

### Task 4: Migration command — import existing threads from agent-service

**Files:** Create `apps/crm/management/__init__.py`, `apps/crm/management/commands/__init__.py`,
`apps/crm/management/commands/import_threads_from_agent_service.py`; Test
`apps/crm/tests/test_migrate_threads.py`

- [ ] **Step 1: Failing test.** With `apps.crm...agent_client.agent_get` mocked to return
  `{"items":[{"id":"t1","org":"Rockefeller","contact_name":"Dr. Okonkwo","contact_email":"a@b.org",
  "stage":"engaged","track":"ai10bn","quintile":4,"traffic_light":"amber","score":0.7,"dossier_id":"d1"}]}`,
  running the command creates an Organization "Rockefeller", a Contact, and an OutreachThread with
  `agent_thread_id="t1"`, `dossier_id="d1"`. Re-running is idempotent (no duplicates — matched on
  agent_thread_id, and on org-name+contact-email vs already-imported rows). `--dry-run` creates nothing.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `Command(BaseCommand)` with `--dry-run`: `from apps.common.agent_client import
  agent_get`; fetch `agent_get("/threads")`; for each item `get_or_create` Organization by name,
  `get_or_create` Contact by (org, email or full_name), `update_or_create` OutreachThread by `agent_thread_id`;
  carry stage/track/score/quintile/traffic_light/dossier_id. Dedup: if an Organization/Contact with the same
  name/email already exists (e.g. from a spreadsheet import) reuse it. Print created/updated/skipped counts.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(crm): one-time migration command pulling threads from agent-service`.

### Task 5: Import wizard — model + parsing + dedup

**Files:** Create `apps/crm/import_wizard.py`; Modify `apps/crm/models.py` (add `CrmImportJob`),
`requirements.txt` (+ openpyxl); Test `apps/crm/tests/test_import_parsing.py`

- [ ] **Step 1: Failing tests.** `parse_rows(file_bytes, filename)` returns a list of dicts (header→value) for
  a `.csv` and an `.xlsx` fixture; `parse_sheet_url(url)` (mock the sheets client) returns the same shape.
  `apply_mapping(rows, mapping)` maps source headers → CRM fields (`org_name, contact_name, contact_email,
  role, stage, track`). `dedupe(mapped_rows)` returns `(new, matched)` where a row whose org_name+email
  already exists in the DB is `matched`. `commit_rows(new_rows)` creates Organization/Contact/OutreachThread
  and returns per-row results (`{row, status: created|error, error?}`); a row missing org_name → error, not
  a crash.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `CrmImportJob(TimestampedUUID)`: workspace FK, `source`(file|sheet),
  `filename`, `sheet_url`, `mapping` JSON, `status`(uploaded|mapped|previewed|committed|failed),
  `results` JSON, `row_count`. `import_wizard.py`: `parse_rows` (csv via stdlib `csv`, xlsx via
  `openpyxl.load_workbook(read_only=True)` — import openpyxl **lazily inside the function** per the
  requirements gotcha), `parse_sheet_url` (reuse `apps/content_intake/sheets_sync` grid reader),
  `apply_mapping`, `dedupe` (case-insensitive org name + email match), `commit_rows` (per-row try/except →
  results, never silent). Add `openpyxl>=3.1,<4.0` to `requirements.txt`. Run `makemigrations crm`.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(crm): import parsing + mapping + dedup + CrmImportJob`.

### Task 6: Import wizard — views + templates (4 steps)

**Files:** Create `apps/crm/views_import.py`, `apps/crm/urls.py` (import routes),
`templates/crm/import/{upload,map,preview,result}.html`; Modify `config/urls.py` (mount `apps.crm.urls`
at `crm/`); Test `apps/crm/tests/test_import_views.py`

- [ ] **Step 1: Failing tests.** GET `/crm/import/` → 200 (upload form) for a campaign_owner/admin/owner,
  403 for others; POST a CSV → 200 mapping step listing the file's headers; POST mapping → 200 preview
  showing new vs matched counts; POST commit → 200 result page with created count + a downloadable error
  report when a row failed. CSP-safe (no inline handlers).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** `_can_manage_crm(request)` = staff or workspace_role in {owner,admin,campaign_owner}.
  Views: `import_upload` (save CrmImportJob, parse headers), `import_map` (store mapping), `import_preview`
  (run dedupe, render new/matched), `import_commit` (commit_rows, render results + errors). HTMX step
  transitions (`hx-post`/`hx-target`). Templates extend `base.html`, BrightBean skin. Mount routes.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(crm): 4-step import wizard (upload/map/preview/commit + error report)`.

### Task 7: CRM UI — Organizations + Contacts (list/detail/CRUD)

**Files:** Create `apps/crm/views.py`, `apps/crm/forms.py`, `templates/crm/{org_list,org_detail,org_form,
contact_list,contact_detail,contact_form}.html`; Modify `apps/crm/urls.py`; Test
`apps/crm/tests/test_crm_views.py`

- [ ] **Step 1: Failing tests.** `/crm/orgs/` lists orgs (filter by tier/type, search by name) — 200 for
  Nduta-role, 403 for viewer; `/crm/orgs/new/` + POST creates an Organization; `/crm/orgs/<id>/` detail shows
  its contacts + threads; same for `/crm/contacts/`. Agent-service is NOT called (pure Django).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** ModelForms for Organization + Contact; list views with `?q`/`?tier`/`?type`
  filters; detail views (org → contacts + threads; contact → threads); CRUD gated by `_can_manage_crm`.
  Templates extend base.html, match the credentials/console list styling.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(crm): organizations + contacts list/detail/CRUD`.

### Task 8: Repoint Joseph surface to Django threads + team thread CRUD

**Files:** Modify `apps/joseph/views.py` (pipeline, brief, thread_drawer, briefs), `apps/joseph/intelligence.py`,
`apps/joseph/readers.py` (keep get_dossier; thread reads now local); Create `apps/crm/thread_views.py`
(edit stage/owner/next-action, log activity, add task) + `templates/crm/_activity_timeline.html`,
`templates/crm/_task_list.html`; Test `apps/joseph/tests/test_pipeline.py` (update),
`apps/crm/tests/test_thread_actions.py`

- [ ] **Step 1: Failing tests.** The pipeline groups `apps.crm.OutreachThread` rows (local DB) by stage — no
  `readers.list_threads` HTTP call; the thread drawer renders an OutreachThread by Django pk; its dossier is
  still fetched via `readers.get_dossier(thread.dossier_id)` (mocked) and agent-down → empty state; POST
  `/crm/threads/<id>/activity/` appends an Activity; POST `/crm/threads/<id>/task/` creates a Task; POST
  `/crm/threads/<id>/edit/` updates stage/owner/next_action.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** Change the Joseph pipeline/brief/thread-drawer/briefs to query
  `apps.crm.OutreachThread` (filter by owner/traffic_light) instead of `readers.list_threads`; the brief's
  L0 maps from the Django thread + `readers.get_dossier(dossier_id)`. Add `apps/crm/thread_views.py` for
  team CRUD + activity/task partials. Keep the existing tests' intent; update mocks from
  `readers.list_threads` → CRM querysets. Dossier refresh posts thread context (Task 9).
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(crm): repoint Joseph pipeline/brief/drawer to Django threads + team thread CRUD`.

### Task 9: Flip the dossier-compile seam (agent-service + Django)

**Files:** Modify (agent-service) `app/api/threads.py` + `app/services/dossier.py`; (agent-service test)
`tests/test_dossier_compile_context.py`; Modify (Django) `apps/joseph/readers.py` (compile posts context),
`apps/crm/thread_views.py` (refresh action); Test `apps/crm/tests/test_dossier_refresh.py`

- [ ] **Step 1: Failing tests.** (agent-service) `POST /agents/dossier/compile` with body
  `{entity, org, contact, track}` runs `build_dossier` using the provided context (no DB thread read) and
  returns `{dossier_id, sources}` (mock the runtime). (Django) `refresh_dossier(thread)` POSTs the Django
  thread's context to that endpoint and stores the returned `dossier_id` on the OutreachThread.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** agent-service: add a context-accepting compile path (keep the old
  `/threads/{id}/dossier` working for back-compat); `build_dossier` accepts an optional `context` dict instead
  of requiring a thread row. Django: `readers.compile_dossier_with_context(payload)` (agent_post) + the
  thread-drawer "Refresh" action calls it and saves `dossier_id`.
- [ ] **Step 4: Run, expect pass** (run agent-service tests with `cd /Users/macbook/Downloads/WAIIS/agent-service
  && /Users/macbook/.local/bin/uv run pytest tests/test_dossier_compile_context.py -q`).
- [ ] **Step 5: Commit** (two commits — one per repo) `feat(dossier): compile from supplied thread context` /
  `feat(crm): dossier refresh posts Django thread context`.

### Task 10: Nav + role gate + TABLE_OWNERSHIP + integration

**Files:** Modify `templates/base.html` (sidebar "CRM" section: Organizations/Contacts/Pipeline/Import,
role-gated), `apps/crm/urls.py` (final routes); Create `docs/TABLE_OWNERSHIP.md`; Test
`apps/crm/tests/test_nav_and_ownership.py`

- [ ] **Step 1: Failing test.** The sidebar shows a "CRM" section (Organizations, Contacts, Pipeline, Import)
  only for users who pass `_can_manage_crm`; `docs/TABLE_OWNERSHIP.md` exists and lists crm tables → Django,
  dossiers/wiki/gate → agent-service.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement.** Add the CRM sidebar section (links via `{% url %}`, gated). Write
  `docs/TABLE_OWNERSHIP.md` per spec §ownership. Ensure all `apps/crm/urls.py` routes are mounted.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(crm): sidebar nav + role gate + TABLE_OWNERSHIP bookkeeping`.

---

## Self-review
- **Spec coverage:** models (T1), scoring port (T2), no-reply (T3), migration (T4), import wizard (T5+T6),
  CRM UI (T7), Joseph repoint + team thread CRUD (T8), dossier seam flip (T9), nav + ownership (T10). All
  spec sections covered. Sequences/mailboxes/grants explicitly deferred (spec Out of scope).
- **Placeholder scan:** none — real code/contracts in each task.
- **Type consistency:** `OutreachThread.agent_thread_id` (T1) used by the migration (T4); `dossier_id`
  (T1) used by repoint (T8) + refresh (T9); `score_thread_features` (T2) used by tasks (T3);
  `_can_manage_crm` (T6) reused (T7, T8, T10); `parse_rows/apply_mapping/dedupe/commit_rows` (T5) used by
  views (T6). Consistent.
- **Build order:** 1→10 (sequential; share models.py/urls.py/base.html/jobs/schedules.py + the Joseph
  surface). Two repos only in T9 (agent-service compile seam).
- After all tasks: full Django suite (deploy gate) + agent-service test for T9. Higher-risk (touches the
  Joseph surface + a one-time migration) — do NOT auto-deploy; verify + deploy with the migration run as a
  manual step.
