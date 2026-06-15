# Agent brain — the closed learning loop (Loop 2) Implementation Plan

> Subagent-driven, TDD, one commit per task. **Two repos:** agent-service (FastAPI, the brain engine —
> agents/episodes/playbooks live here) uses `cd /Users/macbook/Downloads/WAIIS/agent-service &&
> /Users/macbook/.local/bin/uv run pytest <path> -q`; Django (the console UI) uses
> `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <path> -q -p no:warnings`.
> Mock the LLM runtime in tests. Constitutions are FROZEN — never written by any code path. The Gödel rule:
> rubrics/utility are fixed Level-2 artifacts; the Evaluator may not change its own rubric or any constitution.

**Goal:** Close Loop 2 (weekly self-improvement): the Evaluator reads each agent's episodes→outcomes, proposes
≤3 evidence-backed playbook diffs, the diff must pass the agent's eval suite (compliance failure → auto-reject),
a human approves in a Django diff-review UI, the new playbook version hot-swaps, and a nightly rollback-watch
reverts a regression. Builds on existing agent-service primitives (Episode/Outcome/PlaybookVersion/EvalCase/
EvalRun/Learning + the voice_reflect pattern).

**Architecture:** Brain engine in agent-service (`app/services/evaluator.py`, `app/services/evals.py`,
`app/jobs/`), exposed over HTTP; Django console renders + drives approval (generalizing the TB.1 voice-proposal
apply/dismiss pattern). No agent migration (deferred to the strangler-consolidation phase).

---

### Task 1: PlaybookVersion diff schema (agent-service)
**Files:** `app/db/models/agentic.py` (extend PlaybookVersion), Alembic migration; Test `tests/test_playbook_diff_schema.py`
- [ ] Failing test: a `PlaybookVersion` can store `diff_from_previous`, `diff_category`, `evidence_episode_ids`
  (JSON list), `expected_effect`, `metric_to_watch`, `status` (proposed|applied|rejected|rolled_back),
  `approver`, `applied_at`, `rolled_back_at`, `eval_run_id`. Round-trips; defaults sane.
- [ ] Run→fail.
- [ ] Implement the columns (nullable/defaults) + Alembic migration (`alembic revision --autogenerate` or hand);
  keep existing rows valid (status default "applied" for current live versions).
- [ ] Run→pass. Commit `feat(brain): playbook diff/evidence/rollback schema`.

### Task 2: Eval-suite runner + compliance gate (agent-service)
**Files:** `app/services/evals.py`, (extend) `app/db/models/agentic.py` EvalCase (category, mode, input_fixture,
expected, rubric_path), migration; Test `tests/test_eval_runner.py`
- [ ] Failing test: `run_eval_suite(agent_name, playbook_body)` runs every EvalCase for the agent and returns
  `EvalRun(results=[{case_id,passed,score}], overall_pass)`; a failing **compliance**-category case forces
  `overall_pass=False` regardless of others (compliance auto-reject). Hard-assertion cases evaluated in-code;
  llm_judge cases call the runtime (mocked).
- [ ] Run→fail.
- [ ] Implement the runner + the EvalCase field extension + migration; seed 3 sample compliance cases for HERALD
  (status-language trap, confidential-keyword trap, track-cross trap).
- [ ] Run→pass. Commit `feat(brain): eval-suite runner + compliance auto-reject gate`.

### Task 3: Evaluator weekly reflection (agent-service)
**Files:** `app/services/evaluator.py`, `app/jobs/evaluator.py`, register beat; Test `tests/test_evaluator.py`
- [ ] Failing test: `reflect_agent(agent_name, week)` reads the week's Episodes joined to Outcomes, scores the
  bottom episodes, and proposes ≤3 candidate diffs — each with **≥3 evidence_episode_ids** (a diff with <3
  evidence is dropped); each candidate is run through `run_eval_suite` and only `overall_pass=True` candidates
  are stored as `PlaybookVersion(status="proposed")`; a `Learning` memo row is always written (even with 0
  diffs). Generalizes voice_reflect to any agent. Mock the runtime to return a diff proposal.
- [ ] Run→fail.
- [ ] Implement `reflect_agent` + `reflect_all_agents()` Celery/procrastinate weekly job (Fridays) + register in
  the schedule. Schema-enforce the ≥3-evidence rule + the eval gate. Never touch constitutions/rubrics.
- [ ] Run→pass. Commit `feat(brain): generic weekly Evaluator reflection (evidence + eval-gated diffs + memo)`.

### Task 4: Diff apply + rollback watch + API (agent-service)
**Files:** `app/services/playbooks.py` (apply/reject/rollback), `app/jobs/rollback_watch.py`, `app/api/brain.py`
(routes), register router + beat; Test `tests/test_brain_api.py`, `tests/test_rollback_watch.py`
- [ ] Failing tests: `POST /brain/proposals/{id}/apply` (lead) marks the proposed version applied (applied_at,
  approver) and it becomes the latest for (agent,sector); `/reject` marks rejected. `GET /brain/proposals`,
  `GET /brain/learnings`, `GET /brain/eval-runs/{id}` return the review data. `rollback_watch()` reverts an
  applied version whose `metric_to_watch` is below the trailing-4-week baseline for 3 consecutive days →
  sets `rolled_back_at` + reactivates the prior version + writes an urgent Notification.
- [ ] Run→fail.
- [ ] Implement apply/reject/rollback services, the `/brain/*` API (require_role lead for mutations, member for
  reads), the nightly `rollback_watch` job + beat. 
- [ ] Run→pass. Commit `feat(brain): diff apply/reject + nightly rollback watch + /brain API`.

### Task 5: Django console — Learning Log + Diff-review UI
**Files:** Django `apps/intelligence/console_views.py` (+ learning/diff views), `config/console_urls.py`,
`templates/console/{learning_log,diff_review}.html`, `apps/common/agent_client` (reuse); Test
`apps/intelligence/tests/test_learning_console.py`
- [ ] Failing tests: `/console/learning/` lists weekly Learning memos + per-agent diff counts (from
  `GET /brain/learnings`, mocked); `/console/diffs/` lists proposed diffs; `/console/diffs/<id>/` shows the
  side-by-side diff + evidence episodes + eval-run result + Approve/Reject buttons; Approve POSTs to
  `/brain/proposals/<id>/apply` (mocked). Login + role gated; agent-down → empty state, never 500; CSP-safe.
- [ ] Run→fail.
- [ ] Implement the console views + templates (generalize the TB.1 voice-proposal apply/dismiss pattern), the
  agent-client calls, a "Brain" sidebar/console-nav link. 
- [ ] Run→pass. Commit `feat(console): Learning Log + playbook diff-review (approve/reject)`.

---
## Self-review
Coverage: diff schema (T1), eval runner+compliance gate (T2), Evaluator reflection (T3), apply/rollback+API
(T4), console UI (T5) — the full Loop 2. Deferred to brain Slice 2: autonomy-tier promotion/demotion, the
maintenance/self-healing agent, the agents-fleet view. Build order 1→5 (T4 uses T1/T2/T3 outputs; T5 consumes
T4 API). agent-service tasks (1–4) commit on its working branch; Django (5) on a feature branch. Constitutions/
rubrics never modified. After: agent-service suite + Django suite; deploy agent-service (web+worker) + dispatch.
