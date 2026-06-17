# Joseph experience polish — AI approvals + pipeline differentiation + UI uplift

> Subagent-driven, TDD, one commit per task. Tests: `DJANGO_SETTINGS_MODULE=config.settings.test
> /Users/macbook/.local/bin/uv run pytest <p> -q -p no:warnings`. CSP-safe (Alpine @click/hx-*, nonce on
> <script>); desktop templates {% extends "base.html" %}; reuse the BrightBean tokens (.card, .btn-brand,
> font-display Georgia, orange --primary, warm stone). Don't run the whole suite per task.

**Goal:** Fix the three things the principal flagged while testing: (1) AI Approvals is empty, (2) the two
pipelines look identical, (3) Joseph's pages look generic vs the approved preview.

**Grounding:** AI approvals = `Post.objects.filter(review_state=PENDING)` (apps/approvals/console_views.py);
seed_demo creates no Posts → empty. Console pipeline (apps/intelligence/console_views.py) reads the SAME
`apps.crm.OutreachThread` + same stage columns as `apps/joseph/views.py::pipeline` → identical boards. The
approved design is `joseph-ui-preview.html` (on disk, gitignored) — the live Joseph templates under
`templates/joseph/` are flatter than it.

---

### Task 1: Populate AI Approvals (seed pending-review Posts) + verify the bridge
**Files:** Modify `apps/crm/management/commands/seed_demo.py`; Test `apps/crm/tests/test_seed_demo.py` (extend)
- [ ] Failing test: after `seed_demo`, there are ≥3 `composer.Post` with `review_state=PENDING` and
  `review_assignee`=the demo owner (so `/console/approvals` and `/joseph/content` show items).
- [ ] Run→fail.
- [ ] Implement: in seed_demo, create a few realistic HERALD-style draft Posts (workspace=owner's workspace,
  author=owner, review_assignee=owner, review_state=PENDING, a PlatformPost in status `pending_review`,
  captions like the demo content topics) tagged for `--wipe`. Mirror the real shape `draft_post.ensure_draft_post`
  produces. Idempotent.
- [ ] Run→pass. Commit `feat(seed): pending-review demo Posts so AI Approvals populates`.

### Task 2: Differentiate the two pipelines (team vs principal)
**Files:** Modify `apps/intelligence/console_views.py` (pipeline), `templates/console/pipeline.html`,
`apps/joseph/views.py` (pipeline header), `templates/joseph/pipeline.html`; Test
`apps/intelligence/tests/test_console_pipeline.py`, `apps/joseph/tests/test_pipeline.py`
- [ ] Failing tests: `/console/pipeline` is the **Team** board — header "Team pipeline" + subtitle, every card
  shows an **Owner** badge, and there are owner + track filter chips (`?owner=`, `?track=`) that filter the
  threads; `/joseph/pipeline` is the **principal** board — header "My pipeline" (Joseph's), cards do NOT show an
  owner badge (it's his lens). The two pages render visibly different headers + the console-only Owner column.
- [ ] Run→fail.
- [ ] Implement: console pipeline keeps all-owner threads + adds owner/track filters + an Owner badge per card +
  the "Team pipeline" header; Joseph pipeline gets the "My pipeline" header + (optionally) filters to his
  owned+backstop threads. Both still drag-to-restage via `crm:thread-set-stage`.
- [ ] Run→pass. Commit `feat(pipeline): differentiate team (console) vs principal (joseph) boards`.

### Task 3: Joseph UI uplift to the approved preview polish
**Files:** Modify `templates/joseph/{home_desktop,home_mobile,brief,_l0_card,_brief_body,pipeline,thread_drawer,
content_queue}.html`; Test `apps/joseph/tests/test_home.py`/`test_home_desktop.py`/`test_brief.py` (keep green)
- [ ] Failing/guard test: the desktop home renders a branded hero header (assert a new hero wrapper/marker is
  present) and pages stay 200 + role-gated + CSP-safe (no inline handlers; nonce on scripts). Existing assertions
  (charts, action queue, L0 fields) still pass.
- [ ] Run→fail.
- [ ] Implement — read `joseph-ui-preview.html` (the APPROVED design) and bring the live pages up to it:
  - **Hero header** on the desktop home: a branded band (orange `--primary` accent / subtle gradient, Georgia
    `font-display` greeting, date, and a headline stat row) instead of the plain `h1`.
  - **L0 brief card** (`_l0_card`/_brief_body): editorial styling — serif section labels (WHO/WHY NOW/HOOK/RED
    FLAGS/WARM PATH/FRESHNESS), generous spacing, a freshness footer, the L0/L1/L2 toggle as pill buttons.
  - **Pipeline + thread cards**: a left **traffic-light accent border** (red/amber/green), clearer type
    hierarchy (org bold, track/next-action muted), `card-hover-lift` on hover, quintile dots.
  - **Consistent system**: use `.card` + spacing scale; polished empty states ("Everything's warm." etc.);
    mobile keeps the bottom nav. No new colors outside the token set.
  - Keep all existing data + routes + the charts intact; this is styling only.
- [ ] Run→pass. Commit `feat(joseph): UI uplift to the approved preview (hero, editorial briefs, accented cards)`.

---
## Self-review
Coverage: approvals populated (T1), pipelines differentiated (T2), UI uplift (T3) — the three flagged issues.
Build order 1→3 (independent; T2+T3 both touch pipeline.html — T2 first for structure, T3 for styling). After:
full Django suite; deploy dispatch web (+ run seed_demo in prod for the pending Posts). Then resume TB.3/TB.4.
