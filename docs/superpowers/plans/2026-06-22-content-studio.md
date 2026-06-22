# Content Studio — unify Drafts + AI Approval, segment by House/Pillar/Track/Campaign, draft→approve→publish

> Subagent-driven, TDD, one commit per task. Tests per task only:
> `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <p> -q -p no:warnings`.
> CSP-safe (Alpine @click / hx-*, nonce on every <script>); {% extends "base.html" %}; BrightBean tokens
> (.card, .btn-brand, font-display Georgia, orange --primary, warm stone). Orchestrator runs the full suite once
> at the end — not per task.

**Problem (principal-reported, verified in code):** content is fragmented across FOUR surfaces
(`/console/intake/` plan rows, `/console/drafts` agent-service items, `/composer/drafts/` Django draft Posts,
`/console/approvals` pending review) that don't reconcile; the draft `Post` carries **no track/pillar/campaign**
so drafts can't be separated by WAIIS / AI $10bn / pillar; and **approval is decoupled from publish** (approving
a post never makes it publishable — `review_state` and `PlatformPost.status` are separate machines).

**Decisions (confirmed with the principal):**
1. **One Content Studio board** — a single segmented surface listing every draft + pending-review + approved
   post, with review AND publish actions inline. Collapse the four surfaces.
2. **Approve → one-tap Publish** — AI/HERALD drafts must be approved first; once approved a one-tap Publish
   appears (the gate ALWAYS runs). A human author with `publish_directly` can still publish their own.
3. **Segment by House · Pillar · Track · Campaign** — add these to the draft itself, carried from the plan row.

**Grounding (verified):**
- `apps/composer/models.py::Post` — has `workspace` (house), `author`, `caption`, `title`, `review_state`
  (ReviewState: NONE/PENDING/APPROVED/CHANGES_REQUESTED/REJECTED), `review_assignee`; **lacks track/pillar/
  campaign**. `Post.status` is DERIVED from child `PlatformPost.status`
  (draft/pending_review/approved/scheduled/publishing/published/failed). Manager `Post.objects.for_workspace(ws)`.
- `apps/content_intake/models.py::ContentIntake` — has `pillar_theme`, `campaign`, `house`, `sensitivity`,
  OneToOne `post`. `apps/content_intake/owner_routing.py` has the pillar→sector normalization
  (`sector_map`) + `OWNER_BY_PILLAR` (energy→Dennis, agribusiness→Carren, ai→Joseph, digital→Nduta,
  minerals→Dennis) — REUSE for the pillar choice set + normalization.
- Track canonical values: `["core","ai10bn","waiis","programs"]` (apps/crm/models.py:32 comment). Labels:
  Core / AI $10bn / WAIIS / Programs.
- `apps/content_intake/draft_post.py::ensure_draft_post` / `create_post_from_content` — the intake→Post bridge;
  currently copies only title/caption. `_route_for_review` sets review_state=PENDING + review_assignee.
- `apps/approvals/console_views.py` — `ai_approvals` (review_state=PENDING queue), `approval_decide` (sets
  APPROVED + "moves pending_review children toward approved so the publish path can run").
- Publish chain: composer `save_post` action `publish_now`/`schedule` → PlatformPost `scheduled` → Celery
  `poll_and_publish` → **gate** (apps/publisher/engine `_dispatch_to_provider`, the untouchable chokepoint;
  `gate_bypassed=True` only for human direct posts) → provider. DO NOT weaken the gate.
- Nav: `templates/base.html` console section (Ideas/Drafts/Approvals/Pipeline/Intake/News). Joseph's own queue:
  `apps/joseph/views.py::content_queue` + `templates/joseph/content_queue.html` (+ `_can_access_joseph`).

**INVARIANT (do not break):** the gate runs on every publish. AI/HERALD-authored posts must NOT use the
`gate_bypassed` path — only human-authored posts with `publish_directly` may. The one-tap Publish schedules; the
existing Celery chain enforces the gate. Cross-house wall stays (a Post references intake only from its workspace).

---

### Task 1: Segmentation fields on Post + carry-over from intake + backfill + seed + composer selects
**Files:** `apps/composer/models.py` (+migration), `apps/content_intake/draft_post.py`,
`apps/content_intake/segments.py` (new — track/pillar choice sets + normalizers, reuse owner_routing.sector_map),
`apps/composer/views.py` (compose form save), `templates/composer/compose.html` (selects),
`apps/composer/management/commands/backfill_post_segments.py` (new),
`apps/crm/management/commands/seed_demo.py` (set track/pillar/campaign on the demo posts);
Test `apps/composer/tests/test_post_segments.py`, `apps/content_intake/tests/test_draft_segments.py`
- Failing tests: `Post` has `track` (choices core/ai10bn/waiis/programs, blank ok), `pillar` (choices
  energy/agribusiness/ai/digital/minerals, blank ok), `campaign` (CharField). `ensure_draft_post(intake)` copies
  `intake.campaign`→Post.campaign and normalizes `intake.pillar_theme`→Post.pillar via the sector map; track is
  set if inferable (else blank, editable later). The composer save persists track/pillar/campaign edits.
  `backfill_post_segments` populates track/pillar/campaign on existing Posts from their `intake_source`
  (idempotent). `seed_demo` tags its pending demo Posts across ≥2 tracks and ≥2 pillars so the board demos.
- Commit `feat(content): track/pillar/campaign on Post + carry-over from intake + backfill (Content Studio)`.

### Task 2: Approve → one-tap Publish (gate always runs)
**Files:** `apps/composer/views.py` or `apps/publisher/views.py` (a `publish_post` action), `apps/composer/urls.py`,
`apps/approvals/console_views.py` (expose publishable state); Test `apps/composer/tests/test_publish_action.py`
- Failing tests: `POST /composer/posts/<id>/publish/` on an **APPROVED** post transitions its PlatformPosts to
  `scheduled` (effective now) so the existing publish chain runs, and the gate is enforced (NO gate_bypass for
  AI/HERALD posts — assert the dispatched path still gate-checks; reuse the publisher, do not weaken it);
  a post that is **not approved** (review_state PENDING/NONE) and not author+publish_directly is rejected
  (403/blocked) — AI drafts must be approved first; a **human author** with `publish_directly` can publish their
  own directly. Role-gated, CSRF, idempotent (double-publish is safe). Approving (approval_decide) leaves the
  post in a state where this Publish action is allowed.
- Commit `feat(content): one-tap Publish for approved posts via the gate-enforced publish chain (Content Studio)`.

### Task 3: Content Studio unified board — backend view + filtered/segmented query
**Files:** `apps/composer/studio_views.py` (new) or `apps/intelligence/console_views.py`, `config/console_urls.py`;
Test `apps/composer/tests/test_studio_query.py`
- Failing tests: a `content_studio` view at `/console/content` returns, for the active workspace, ALL relevant
  posts unified across states — draft, pending_review, approved(not yet published), scheduled, published(recent)
  — as one list with a state label per card; supports filters `?track=&pillar=&house=&campaign=&state=&q=` that
  narrow the set (each independently and combined); returns per-segment counts (e.g. counts by track and by
  pillar) for the chips; respects `for_workspace` scoping (cross-house wall). Pure query/context — no 500 on
  empty. (House filter = workspace; within the active workspace the "house" chip is informational unless multiple
  houses are visible to the user.)
- Commit `feat(content): Content Studio unified board query (state + track/pillar/campaign filters) (Content Studio)`.

### Task 4: Content Studio board UI + nav reconciliation
**Files:** `templates/console/content_studio.html` (new), `templates/console/_studio_card.html`,
`templates/base.html` (nav: add "Content Studio"; redirect/relabel Drafts + Approvals),
`apps/approvals/console_views.py` + `config/console_urls.py` (redirect old routes to the studio or render as
filtered studio views); Test `apps/composer/tests/test_studio_ui.py`
- Failing tests: `GET /console/content` renders the board — filter chips for track / pillar / house / campaign /
  state (each a `?param=` link, no inline JS), segment grouping with the counts from T3, and per-card status
  badge + inline actions by state: **pending_review** → Approve / Request changes / Reject (POST to
  approval_decide); **approved** → **Publish** (POST to the T2 action); any → **Edit** (link to composer). The
  old `/console/drafts` and `/console/approvals` redirect to (or render within) the studio. Role-gated; CSP-safe
  (nonce'd scripts, Alpine/hx-* only); responsive (chips wrap, cards grid `grid-cols-1 md:grid-cols-2 xl:grid-cols-3`).
- Commit `feat(content): Content Studio board UI + collapse the 4 draft surfaces into one (Content Studio)`.

### Task 5: Joseph alignment (his content queue uses the same segmented approve→publish flow)
**Files:** `apps/joseph/views.py::content_queue`, `templates/joseph/content_queue.html`; Test
`apps/joseph/tests/test_content_queue.py` (extend)
- Failing tests: `/joseph/content` shows Joseph's posts (his pillar/owned + assigned-to-him) with the SAME
  segmentation badges (track/pillar/campaign) and the SAME inline actions — Approve (where he is the assignee)
  and one-tap Publish (when approved) — consistent with the studio; filters by track/pillar work; stays 200 +
  `_can_access_joseph` + CSP-safe. Links to the full Content Studio.
- Commit `feat(joseph): align Joseph's content queue with the segmented Content Studio approve→publish flow`.

---
## Self-review
Maps to the three complaints + the three confirmed decisions: segmentation fields + carry-over (T1) → approve→
publish alignment (T2) → unified board query (T3) → board UI collapsing the 4 surfaces (T4) → Joseph consistency
(T5). The gate stays untouchable (T2 schedules; the existing chain gate-checks; no bypass for AI content).
Sequential & dependent (shared Post model + composer/approvals + nav + templates) → build one at a time, each
build→review→fix. After all 5: full Django suite, deploy dispatch web, run backfill + reseed in prod, smoke.
