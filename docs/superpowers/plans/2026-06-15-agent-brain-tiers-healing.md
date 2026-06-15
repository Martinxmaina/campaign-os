# Agent brain Slice 2 — autonomy tiers + self-healing + fleet view

> Subagent-driven, TDD, one commit per task. agent-service: `cd /Users/macbook/Downloads/WAIIS/agent-service
> && /Users/macbook/.local/bin/uv run pytest <p> -q`. Django: `cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform
> && DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <p> -q -p no:warnings`.
> Mock the LLM runtime. Constitutions/rubrics FROZEN. No-trace-no-fix: self-healing must cite trace IDs or stop.

**Goal:** Complete the brain's safety + observability: code-enforced autonomy-tier promotion/demotion with an
evidence ledger (protected classes T2-capped), a maintenance/self-healing loop (breaker trip → trace RCA →
HealingIncident + fix routing), episode-driven breaker evaluation, and a Django agents-fleet + breakers +
healing console. Builds on existing AutonomyTier (core.py + tiers.py), Breakers (Slice F), HealingIncident,
Episode/Outcome/Trace, and the Loop-2 `/brain` API.

**Architecture:** engine in agent-service; Django console reads `/brain` over HTTP (same as Loop 2).

---

### Task 1: Autonomy-tier promotion/demotion engine (agent-service)
**Files:** `app/services/tiers.py` (extend), `app/db/models/core.py` (AutonomyTier: + since, evidence_episode_ids,
last_reviewed if missing), migration, `app/jobs/tier_review.py` + beat; Test `tests/test_tier_review.py`
- [ ] Failing tests: `review_tiers()` promotes an action_class from T0→T1 (then T1→T2) when the trailing
  4-week acceptance rate (from Outcomes: approvals vs rejections for that agent/action_class) ≥0.90 and the
  window has ≥N samples, recording `evidence_episode_ids` + `since`; **never promotes a protected class past T2**
  (cap=t2_permanent); demotes one tier on a logged incident (HealingIncident or a gate-rejection spike) or a
  sustained KPI miss. Idempotent.
- [ ] Run→fail.
- [ ] Implement the promotion/demotion logic + the AutonomyTier field additions + migration + a nightly
  `tier_review` job registered in the schedule. Keep `resolve_tier()` enforcement intact.
- [ ] Run→pass. Commit `feat(brain): autonomy-tier promotion/demotion + evidence ledger (protected T2 cap)`.

### Task 2: Episode-driven breaker evaluation (agent-service)
**Files:** `app/services/breakers.py` (extend `evaluate`), Test `tests/test_breaker_episode_eval.py`
- [ ] Failing test: `evaluate()` computes error_rate (status=error episodes / total), cost_day (sum cost_usd),
  and gate_rejection_rate from **Episodes** in the window (not just JobRun) and trips the matching Breaker when
  a threshold is crossed; below threshold → no trip. (Keeps existing JobRun signals.)
- [ ] Run→fail.
- [ ] Implement episode-based metric computation in `evaluate`.
- [ ] Run→pass. Commit `feat(brain): breakers evaluate error/cost/gate-rejection from episodes`.

### Task 3: Maintenance / self-healing loop (agent-service)
**Files:** `app/services/maintenance.py`, `app/db/models/agentic.py` (HealingIncident: + fix_type, root_cause_md,
pr_url, status if missing), migration, `app/jobs/maintenance.py` + trigger on breaker trip; Test
`tests/test_maintenance.py`
- [ ] Failing tests: `diagnose(breaker_or_window)` queries Traces for the failure window; with trace evidence it
  writes a `HealingIncident(root_cause_md, trace_ids, fix_type)` where fix_type routes config/prompt →
  `status=fix_proposed` (a reflection-style proposal, NOT applied) and code → `status=fix_proposed` with a
  pr_url note (no auto-merge, never to main); with **no trace evidence → `status=insufficient_evidence`, stop**
  (no guessing). Triggered when a breaker trips.
- [ ] Run→fail.
- [ ] Implement `maintenance.diagnose` (LLM RCA mocked in tests, schema-enforced no-trace→insufficient_evidence)
  + HealingIncident field additions + migration + the breaker-trip → maintenance hook (+ a periodic safety sweep).
- [ ] Run→pass. Commit `feat(brain): self-healing maintenance (trace RCA -> healing incident, no-trace-no-fix)`.

### Task 4: /brain API — tiers, healing, fleet status (agent-service)
**Files:** `app/api/brain.py` (extend), Test `tests/test_brain_fleet_api.py`
- [ ] Failing tests: `GET /brain/tiers` (per agent/action_class tier + since + evidence count), `GET /brain/healing`
  (incidents), `GET /brain/fleet` (per agent: status, tiers, open breakers, last-7d episode count + cost +
  gate-pass rate, learnings count) — all member-gated, returning JSON the console renders.
- [ ] Run→fail.
- [ ] Implement the three read routes aggregating the above.
- [ ] Run→pass. Commit `feat(brain): /brain tiers + healing + fleet status API`.

### Task 5: Django console — agents fleet + breakers + healing
**Files:** `apps/intelligence/console_views.py` (+ fleet/breakers/healing views), `config/console_urls.py`,
`templates/console/{agents_fleet,breakers,healing}.html`; Test `apps/intelligence/tests/test_fleet_console.py`
- [ ] Failing tests: `/console/agents/` renders a card per agent (status, tier per action_class, open breakers,
  7d episodes/cost/gate-pass, learnings) from `GET /brain/fleet` (mocked); `/console/breakers/` lists breakers +
  a Reset action (POST → `/breakers/<id>/reset`); `/console/healing/` lists incidents. Login+role gated;
  agent-down → empty state (never 500); CSP-safe.
- [ ] Run→fail.
- [ ] Implement the three console views + templates + nav links (BrightBean skin, reuse agent_client).
- [ ] Run→pass. Commit `feat(console): agents fleet + breakers + healing incidents`.

---
## Self-review
Coverage: tiers (T1), episode-breaker eval (T2), self-healing (T3), API (T4), console (T5) — completes the
brain's autonomy + Loop-3 (self-healing) + observability. Loop 1 (in-run self-correction via breakers) + Loop 2
(reflection, prior slice) now both closed. Constitutions/rubrics frozen; no-trace-no-fix enforced; protected
classes T2-capped in code. Build order 1→5 (T4 exposes T1/T2/T3; T5 consumes T4). After: both suites; deploy
agent-service web+worker + dispatch web+worker.
