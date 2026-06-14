export const meta = {
  name: 'ghost-nexus-channel',
  description: 'Build the Ghost (Nexus Brief) publish channel from the plan, task-by-task with spec gates, then adversarial review + fix + full suite',
  phases: [
    { title: 'Implement', detail: 'plan tasks 1-10, sequential, TDD, spec-gated' },
    { title: 'Review', detail: 'parallel adversarial review (security/correctness/tests)' },
    { title: 'Verify', detail: 'confirm findings' },
    { title: 'Fix', detail: 'apply confirmed fixes, full suite green' },
  ],
}

const REPO = '/Users/macbook/Downloads/WAIIS/waiis-dispatch-platform'
const PLAN = `${REPO}/docs/superpowers/plans/2026-06-11-ghost-nexus-channel.md`
const SPEC = `${REPO}/docs/superpowers/specs/2026-06-11-ghost-nexus-channel-design.md`
const BRANCH = 'feature/ghost-nexus-channel'
const BASE_SHA = 'e16f56e'
const TEST_ENV = `cd ${REPO} && export PATH="$HOME/.local/bin:$PATH"`

const TASKS = [
  { n: 1, name: 'Platform enum + AuthType.API_KEY + char limit' },
  { n: 2, name: 'Ghost Admin JWT (stdlib)' },
  { n: 3, name: 'GhostProvider — connect/profile + Post-mode publish' },
  { n: 4, name: 'GhostProvider — Newsletter (email-only) mode' },
  { n: 5, name: 'Register provider + env fallback' },
  { n: 6, name: 'Credentials form fields (optional newsletter_slug)' },
  { n: 7, name: 'Connect Ghost → one org-level SocialAccount' },
  { n: 8, name: 'Engine — inject title + publish-as for Ghost' },
  { n: 9, name: 'Composer — surface org Ghost account + Post/Newsletter toggle' },
  { n: 10, name: 'Rotate/redact leaked secrets in docs/ghost.md (note: file is UNTRACKED — gitignore it instead of committing secrets)' },
]

const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED'] },
    summary: { type: 'string' }, pytest: { type: 'string' },
    commit: { type: 'string' }, concerns: { type: 'string' },
  },
  required: ['status', 'summary', 'pytest', 'commit'],
}
const SPEC_SCHEMA = {
  type: 'object',
  properties: { compliant: { type: 'boolean' }, issues: { type: 'array', items: { type: 'string' } } },
  required: ['compliant', 'issues'],
}

function implPrompt(t) {
  return `You are implementing exactly ONE task from an approved implementation plan.

Read the plan: ${PLAN}
Execute **Task ${t.n}: ${t.name}** — every checkbox step in order: write the failing test FIRST, run it to confirm it fails, implement, run green, commit with the message the task gives. The plan has complete code; use it, BUT this branch already contains a recent "Accounts & Credentials Hub" refactor — so READ the current state of any file you touch (esp. apps/credentials/views.py, platform_fields.py, account_hub.py, templates/credentials/list.html, apps/composer/views.py) and ADAPT the plan's code to what's actually there rather than blindly pasting. Preserve existing behaviour.

Work in ${REPO} on branch ${BRANCH} (verify: git branch --show-current; if different, STOP → BLOCKED).
Run tests: ${TEST_ENV} && uv run python -m pytest <paths> -q

Hard rules:
- Scope = ONLY Task ${t.n}. No other tasks, no unrelated refactors.
- Do NOT touch /Users/macbook/Downloads/WAIIS/agent-service.
- TDD: the failing test must genuinely fail first.
- Run the nearest existing app suite for files you touched (e.g. apps/credentials, apps/composer, apps/publisher) to confirm no regressions.
- Do NOT run the FULL suite (it shares one test DB; the workflow runs it once at the end).
- Commit only the task's files (+ uv.lock if deps changed). For Task 10, docs/ghost.md is UNTRACKED — redact secrets in place AND add 'docs/ghost.md' to .gitignore so secrets never enter git; commit only the .gitignore change.
- If the plan's assumption doesn't match reality and the fix is mechanical, adapt + note it; if it needs a design decision, return BLOCKED with specifics.

Return structured output: status, summary (what you did + any adaptation), pytest (exact summary lines for your new tests + the app-suite check), commit (git rev-parse --short HEAD), concerns.`
}
function specPrompt(t, impl) {
  return `Spec-compliance reviewer. Do NOT trust the report — verify by reading the actual code on branch ${BRANCH} in ${REPO}.

Requirements: **Task ${t.n}: ${t.name}** in ${PLAN}.
Implementer claims: ${JSON.stringify(impl)}

Inspect the task's commit(s) (git log --oneline -5; git show <sha> --stat; read changed files). Verify: every required artifact present + matching the task's intent (adapted correctly to the hub-refactored code is fine); the test asserts real behaviour (not hollow); nothing extra; names/signatures match the plan (ghost_admin_jwt, GhostProvider, content.extra["title"]/["ghost_publish_as"], required_field_keys, available_accounts_for). Run the task's tests yourself (${TEST_ENV} && uv run python -m pytest <task paths> -q) — must pass.

Return: compliant (true only if all checks pass AND tests green when you run them), issues (specific, file:line, empty if compliant).`
}
function fixPrompt(t, issues) {
  return `Fix spec-compliance issues on **Task ${t.n}: ${t.name}** (plan ${PLAN}) in ${REPO} branch ${BRANCH}. Fix ALL, minimally:
${issues.map((i) => '- ' + i).join('\n')}
Re-run the task's tests green, amend/add a commit. Return structured output: status, summary, pytest, commit, concerns.`
}

phase('Implement')
const implemented = []
for (const t of TASKS) {
  let impl = await agent(implPrompt(t), { label: `impl:T${t.n}`, phase: 'Implement', schema: IMPL_SCHEMA })
  if (!impl) { log(`Task ${t.n}: agent skipped — aborting`); break }
  if (impl.status === 'BLOCKED') {
    implemented.push({ task: t.n, status: 'BLOCKED', detail: impl.summary })
    log(`Task ${t.n} BLOCKED — stopping for human decision: ${impl.summary.slice(0, 160)}`)
    break
  }
  let gate = await agent(specPrompt(t, impl), { label: `spec:T${t.n}`, phase: 'Implement', schema: SPEC_SCHEMA })
  let rounds = 0
  while (gate && !gate.compliant && rounds < 2) {
    rounds += 1
    impl = await agent(fixPrompt(t, gate.issues), { label: `fix:T${t.n}.${rounds}`, phase: 'Implement', schema: IMPL_SCHEMA })
    gate = await agent(specPrompt(t, impl), { label: `spec:T${t.n}.${rounds}`, phase: 'Implement', schema: SPEC_SCHEMA })
  }
  implemented.push({ task: t.n, status: impl.status, commit: impl.commit, pytest: impl.pytest, specCompliant: gate ? gate.compliant : false, concerns: impl.concerns || '' })
  log(`Task ${t.n} done (spec ${gate && gate.compliant ? 'PASS' : 'UNRESOLVED'})`)
}

const blocked = implemented.filter((r) => r.status === 'BLOCKED' || r.specCompliant === false)
if (implemented.length < TASKS.length || blocked.length) {
  return { halted: true, implemented, blocked, note: 'Halted or a spec gate unresolved — human decision needed before review.' }
}

const FINDINGS = {
  type: 'object',
  properties: { findings: { type: 'array', items: { type: 'object', properties: {
    title: { type: 'string' }, file: { type: 'string' },
    severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
    detail: { type: 'string' }, fix: { type: 'string' },
  }, required: ['title', 'file', 'severity', 'detail', 'fix'] } } },
  required: ['findings'],
}
const DIMENSIONS = [
  { key: 'security', prompt: `Review the Ghost channel (git diff ${BASE_SHA}..HEAD in ${REPO}) for SECURITY: the Admin secret/JWT never logged; secret hex-decode correct; SSRF on base_url (Ghost calls go to a configurable URL — only the configured site, no user-controlled host injection); the leaked key handling (docs/ghost.md untracked + gitignored, NOT committed); credentials masked in UI; connect view requires org admin (_can_manage).` },
  { key: 'correctness', prompt: `Review (git diff ${BASE_SHA}..HEAD in ${REPO}) for CORRECTNESS: post vs newsletter URL/email_only logic; newsletter-without-slug fails loudly; ONE org-level SocialAccount (idempotent, no per-workspace dupes); org ghost account surfaced in every workspace's composer without leaking OTHER orgs' accounts; title from Post; gate still authoritative for ghost; JWT exp/iat (5 min).` },
  { key: 'tests', prompt: `Review (git diff ${BASE_SHA}..HEAD in ${REPO}) for TEST QUALITY: tests assert real behaviour, mock httpx (no live network); newsletter/missing-slug/connect-idempotency/org-visibility/engine-extra all covered; no test depends on the shared full-suite run; credentials hub regressions covered.` },
]

phase('Review')
const reviewed = await pipeline(
  DIMENSIONS,
  (d) => agent(d.prompt + '\n\nReturn structured findings; empty if clean; file:line specifics.', { label: `review:${d.key}`, phase: 'Review', schema: FINDINGS }),
  (rev, d) => parallel((rev.findings || []).map((f) => () =>
    agent(`Adversarially verify against actual code in ${REPO} (branch ${BRANCH}). REAL defect that should block merge? Default refuted for style nits / impossible-in-this-deployment.\n\nFinding: ${JSON.stringify(f)}`,
      { label: `verify:${d.key}`, phase: 'Verify', schema: { type: 'object', properties: { real: { type: 'boolean' }, reason: { type: 'string' } }, required: ['real', 'reason'] } })
      .then((v) => ({ ...f, dimension: d.key, verdict: v }))
  )),
)
const confirmed = reviewed.flat().filter(Boolean).filter((f) => f.verdict && f.verdict.real)
log(`Review complete: ${confirmed.length} confirmed findings.`)

phase('Fix')
let fixSummary = 'No confirmed findings.'
if (confirmed.length) {
  fixSummary = await agent(`Apply minimal fixes for these confirmed findings in ${REPO} (branch ${BRANCH}), then run the FULL suite green ALONE (${TEST_ENV} && uv run python -m pytest -q --create-db) and commit.\n\n${JSON.stringify(confirmed, null, 2)}\n\nReturn what changed + the final pytest summary line.`, { label: 'fix:apply', phase: 'Fix' })
} else {
  fixSummary = await agent(`Run the FULL suite ALONE in ${REPO}: ${TEST_ENV} && uv run python -m pytest -q --create-db. Report the exact final summary line. If anything fails (and it's a real regression from this branch, not a stale-DB artifact), fix minimally + commit, then report.`, { label: 'fix:full-suite', phase: 'Fix' })
}

return { implemented, confirmed_findings: confirmed, fix_summary: fixSummary }
