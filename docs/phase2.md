# Campaign OS — Full System Build Specification
**Version 1.0 · 14 June 2026 · INTERNAL ONLY**
**Executor:** Claude Code
**Owner:** Joseph Nganga (principal) · Nduta Njenga (campaign owner) · Lazarus Magwaro (tech lead)

---

## 1. What This System Is

Campaign OS is AfCEN's internal operating system for resource mobilisation.
AfCEN is not a startup raising equity. It is an African development and
climate infrastructure organisation that raises:

- **Philanthropic and bilateral grants** — to fund the AI $10Bn Technical
  Secretariat ($1.5–2M anchor ask within a $3.5–5M Phase I envelope from
  Rockefeller, Schmidt Futures, GEAPP, Gates, IKEA, GIZ, IDRC, KOICA).
- **Core operational funding** — unrestricted grants for AfCEN's runway
  (Elumelu, Mo Ibrahim, Mastercard, Ford, Hewlett).
- **Programme grants** — specific project funding.
- **Event sponsorship** — for WAIIS 2026 (the West Africa Integration &
  Investment Summit, Freetown, 16–19 November 2026), sponsored by DFIs,
  sovereign wealth funds, and corporates in exchange for Deal Room access
  and brand association with a Head-of-State-convened platform.

**There is no equity, no cap table, no token, no investor onboarding.**
The confidential keywords in the gate exist because these terms would
catastrophically misrepresent AfCEN if they appeared in external
communications. The gate is existential, not procedural.

Campaign OS replaces: spreadsheet tracking, manual content drafting,
email-based approval chains, and ad-hoc research. It does not replace
human judgment on any high-stakes external communication.

---

## 2. The Ultimate User Experience

### 2.1 Joseph's Experience (the principal)

Joseph opens Campaign OS on his phone at 7am before flying to London
for a day of funder meetings.

The home screen shows three things:
- Today's meetings with brief cards pre-loaded: "Rockefeller Foundation
  VP, 2pm. Brief: they recently committed $40M to digital-public-
  infrastructure in East Africa. Recommended hook: the Secretariat as
  the operational engine for their existing thesis. Red flag: confirm
  the SE4ALL TA figure with Will before citing it. Warm path: Dr. Amina
  via Mission 300."
- His action queue: two gate escalations to approve, one deck review,
  one post waiting for his sign-off.
- A red thread: Schmidt Futures has been silent for 11 days.

He taps to approve the gate escalation on the AI 10Bn post (a draft
the WAIIS team inadvertently crossed tracks on — the gate caught it).
One tap, flagged phrase highlighted, reason shown, approve.

He reads the Rockefeller brief card on the plane, no internet needed
(cached offline). He walks into the meeting briefed.

After the meeting, Campaign OS sends a notification: "Just finished
with Rockefeller — capture now." He holds the record button for 90
seconds and talks. The system extracts: three commitments (a follow-up
call with the grants committee, an intro to the Ford Foundation Africa
VP, and an expression of interest in anchoring Phase I), two next steps,
and one content idea (they asked specifically about the energy-compute
nexus, which no one has written about yet). One tap confirms it all.

That evening, HERALD has drafted a follow-up email in Joseph's voice —
direct, no hedging, 3 paragraphs. The deck for the grants committee
meeting (a philanthropy_anchor skeleton for the AI 10Bn track with the
Ford Foundation warm path built into the opening slide) is ready for
review. Joseph edits one slide on his laptop: "Make the ask slide more
direct." The agent edits only that slide, re-verifies it against the
gate, and updates the deck in the same browser tab.

The Ford Foundation intro surfaces in the action queue the next morning
as a task: "Send intro email to Ford Africa VP (drafted, gate-cleared,
in your voice)." He edits the email slightly and sends it from his
connected Gmail.

**Joseph never logs into a CRM. He never creates a task. He never
searches for information about a funder. The system does all of that,
surfaces the relevant slice, and asks only for his judgment.**

### 2.2 The Content Team's Experience (Nduta, Dennis, Carren, Roberto)

Nduta opens Campaign OS on Monday morning. The Sunday deliberation has
run. The ideas queue shows 12 proposals, each with a rationale chain:
"LinkedIn post on the energy-compute nexus (AfCEN house) — signal: IEA
released a data-centre energy report Friday (credibility: high);
pipeline context: Rockefeller conversation last week surfaced this as
their primary thesis; format: data-led posts outperformed contrarian
2:1 this month. Suggested angle: 'African data centres will consume X%
of new power generation by 2035 — here's why that's the unlock, not
the problem.'"

She accepts 7, edits 2, rejects 3. HERALD drafts all 9 immediately.

Dennis opens his personal queue. He sees a post in his voice waiting
for review — drafted from an idea he submitted to the intake board
last week about the Lobito corridor. The KALRO partnership post is
also there but marked blocked: "Awaiting partner permission from
Carren (due: 18 June)." He can see it, can't schedule it.

The content calendar for the week fills automatically with the accepted
drafts slotted into the best-performing time windows per house. Dennis
can drag and drop if he wants a different slot. He composes a post
directly — types a rough angle, HERALD polishes it in his voice with
the inline gate check underlining "our AI 10Bn partnership is now
confirmed" in red (status language without a signed source). He removes
the word "confirmed." It clears.

By Thursday, the Nexus Brief is assembled. JARVIS has drafted the four
sections. The "From Joseph's desk" section is in Joseph's queue. He
approves it with a one-line edit. It publishes Thursday noon.

**The content team creates and decides. The agents draft, schedule,
enforce compliance, and learn from every approval and rejection.**

### 2.3 The Platform as a Whole

Every Friday, the team gets a digest — written by HERALD about the
agents:

"This week: 23 posts published (21 passed gate first try, 2 required
edits — both status language on the WAIIS track). 4 funder dossiers
refreshed. 1 grant opportunity flagged (FCDO RLTA window closes
14 July — assigned to Nduta). 3 Wave-1 threads advanced: Schmidt
Futures moved from engaged to proposal_sent; GEAPP meeting confirmed
for 22 June; Rockefeller follow-up call scheduled. Content multiplier
vs. Week 1 baseline: 6.2×. Agent fleet cost this week: $34. HERALD
v14 proposed two playbook diffs — one approved (lead with a statistic
on AfCEN posts), one pending your review."

The team sees the engine working. They trust it because it shows its
work.

---

## 3. Architecture (Final, Definitive)

### 3.1 One Django Project
Everything lives in a single Django 5 project — the rebranded fork of
BrightBean Studio, renamed **Campaign OS**. This project contains:
- All UI (every view, every module, every mobile screen).
- All agent execution (MAF runtime, constitutions, playbooks).
- All jobs (Celery tasks, Celery beat schedules).
- All integrations (Google Calendar, Gmail, Sheets, Slides, Firecrawl,
  DocSend — in-process, no external workflow orchestrator).
- The compliance gate (both passes).
- The knowledge wiki (the LLM wiki — Karpathy pattern).
- The self-learning loops.

**n8n is fully removed.** Every integration is a Celery task or a
Django webhook view. One codebase, one deployment, one place to debug.

### 3.2 The Strangler Migration
Phase 0 stood up a FastAPI agent service. The strangler migration
moves everything into Django capability by capability:
1. Celery + Redis up (TB.0).
2. Gate shadow-mode (Django gate runs alongside FastAPI gate; parity
   required for 2 weeks before cutover).
3. Knowledge / ingestion / Firecrawl jobs.
4. Agent harness + HERALD.
5. Deliberation + full content pipeline.
6. Joseph's intelligence layer + deck module.
7. FastAPI decommissioned before Phase 3.

**Rule:** every table is owned by exactly one migration system at a
time. Alembic until cutover, Django migrations after. A table's
ownership transfers in a single commit; no half-states.

### 3.3 Django App Map
```
campaign_os/                # project root
  settings/                 # base, dev, prod
  urls.py
  celery.py                 # Celery app + beat schedule

apps/
  core/                     # User, RBAC, audit_log, base models
  gate/                     # Pass 1 (rules/yaml), Pass 2 (agent)
  agents/                   # MAF runtime, constitutions (read-only),
  |                         # playbooks, rubrics, eval system
  ingestion/                # ingest_items, routing, Firecrawl client,
  |                         # monitored_sources, wiki compile
  knowledge/                # knowledge_pages, revisions, MemoryStore
  content/                  # content_intake, content_items, ideas,
  |                         # composer, curation, calendar agent
  crm/                      # organizations, contacts, outreach_threads,
  |                         # activities, tasks, sequences, dossiers
  decks/                    # blocks, deck_templates, deck_registry,
  |                         # assembly agent, Slides API client
  grants/                   # grants, monitoring, triage
  learning/                 # eval_cases, eval_runs, playbook_versions,
  |                         # reflection loop, healing_incidents
  notifications/            # notification engine, channels (Celery)
  integrations/             # google_calendar, gmail, google_sheets,
  |                         # google_slides, docsend, r2
  webhooks/                 # all inbound webhooks (HMAC verified)
  publishing/               # inherited from fork: platform connections,
  |                         # publish pipeline, inbox, media library
  waiis/                    # Phase 3: summit-specific models + views

  modules/                  # UI module apps (HTMX views)
    home/
    pipeline/
    content_board/
    ideas/
    composer/
    agents_view/
    learning_log/
    knowledge_browser/
    admin_panel/
    waiis_ops/
    joseph/                 # Joseph's personal surfaces
```

### 3.4 Infrastructure
- **Django + Gunicorn** on Railway (web process).
- **Celery worker** on Railway (background tasks).
- **Celery beat** on Railway (scheduled tasks — one process, one
  `schedules.py` file listing every schedule).
- **Redis** on Railway: Celery broker + results backend + Django cache
  + Django Channels layer + rate limiting + distributed locks.
- **Postgres** on Railway (existing instance): pgvector enabled.
- **Cloudflare R2**: media uploads, voice notes, deck assets.
- **Firecrawl** self-hosted on Azure Container Apps (existing):
  `FIRECRAWL_BASE_URL` + `FIRECRAWL_API_KEY` in vault. Probe on boot.
- **Google Slides API**: deck assembly.
- **Ghost**: Nexus Brief (direct API, no webhook intermediary).
- **DocSend / Google Drive**: data rooms (webhooks inbound).

### 3.5 The Gate (Non-Negotiable Architecture)
Two passes on every external communication — post, email, deck,
newsletter, brief — before it can be sent, published, or delivered.

**Pass 1 (deterministic, synchronous, in-process):**
Rules in `gate/rules/*.yaml`. Categories:
- `status_language`: flag "secured|committed|funded|approved|signed|
  confirmed" without a `signed_source_ref`.
- `confidential`: HARD BLOCK — "ECTA|ADGM|token|cap table|
  capitalization table|valuation|carry|seed round|founder ownership|
  internal financials". These terms stop everything. They never route
  to a human. They die at the gate.
- `track_separation`: WAIIS content cannot reference AI 10Bn blocks;
  AI 10Bn content cannot reference WAIIS blocks.
- `countdown_milestone`: (Phase 3) WAIIS countdown content must carry
  a `milestone_ref` field; absent = flag.
- `deal_confidential`: (Phase 3) instrument amounts/parties = hard block
  unless `status=announced`.

**Pass 2 (semantic, agent, async):**
- Implied commitments not caught by Pass 1.
- Projections stated as fact (must read: "the Initiative's published
  projections estimate…").
- Partner-separation nuance.
- Untrue FOMO (a claim that sounds like momentum but cites nothing).
- Unverified figure discipline: numeric claims in drafts must trace to
  an approved block, a wiki citation, or a proof_point marked confirmed.

**Routing:**
- Clean → publish per autonomy tier.
- Flag → topic lead / Nduta; numbers/named partners/status → Joseph
  (or his delegate); WAIIS political → Kandeh + Joseph.
- Block → dead. Never routes. Logged to audit.

**The gate hook:** patched into the fork's publish task. Nothing
publishes from the platform — including content a human types directly
into the native editor — without a valid `gate_id` with verdict
`pass|approved`. Two enforcement layers: gate middleware in the Django
app AND the hook in the publishing pipeline. Defense in depth.

### 3.6 Agent Architecture
Each agent is five components. The prompt is the smallest.

**Five components:**
1. **Constitution (frozen file, git-read-only):** compliance rules,
   escalation rules, brand-house boundaries. Never modified by any
   code path. Constitutions are reviewed by Joseph before Phase 1 and
   change only via a PR with Joseph's sign-off.
2. **Playbook (versioned row in `playbook_versions`):** craft — voice
   heuristics, hook patterns, search strategies, scoring weights,
   format rules. This is what the reflection loop improves.
3. **Tools + memory:** scoped tool access (each agent has a defined
   tool budget); wiki-first memory (L0/L1/L2 from `knowledge_pages`
   before any web call); episodic memory (`episodes` + `outcomes`);
   pgvector semantic index.
4. **Eval suite:** 20+ cases per agent in `eval_cases`, including
   compliance traps. Every playbook diff must pass the full suite
   before being applied.
5. **Self-correction loop:** plan → act → verify own output against
   rubric → revise → submit. Runtime circuit breakers (error rate,
   gate-rejection rate, cost per output) pause the agent and page
   Lazarus.

**The agents:**
- **HERALD:** content drafting + repurposing. One instance per brand
  house voice (AfCEN, WAIIS, AI 10Bn, Joseph personal). Learns via
  weekly reflection what hook patterns, formats, and angles work per
  house and per audience.
- **JARVIS:** long-form assembly. The Nexus Brief. Multi-section
  documents. Takes section drafts from HERALD and assembles them.
- **ATLAS:** research intelligence. Orchestrator-worker — spawns
  parallel subagents for deep research. Reads wiki first, web second.
  Builds and maintains funder dossiers. Runs the wiki compile job.
  Monitors news and surfaces signal to the curation queue.
- **FORGE:** grant intelligence. Watches portals, matches opportunities
  to tracks, generates fit rationale, schedules deadline alerts.
- **DEAL-ENGINE:** pipeline scoring. Transparent weighted model in its
  playbook. Scores contacts and threads. Calibration data (quintile ×
  reply rate) feeds the calibration chart. Learns to re-weight signals
  from outcome data.
- **Deck agent:** assembles pitch decks from the block library. Writes
  the personalization layer. Interfaces with Google Slides API. Handles
  Joseph's section-level edit requests.
- **Evaluator:** the meta-agent. Runs the weekly reflection cycle per
  agent. Scores episodes against fixed rubrics. Proposes playbook diffs
  with evidence. Never modifies constitutions.
- **Maintenance agent:** self-healing. Triggered by circuit breaker
  trips. Queries traces for root cause. Config/prompt fixes → the
  reflection pipeline. Code fixes → GitHub PR. Never touches main.

**The editorial deliberation (Sunday, 20:00 EAT):**
MAF graph workflow:
1. ATLAS signals step: reads this week's `knowledge_page_revisions`,
   high-trust `ingest_items`, tentpole calendar, grant deadlines within
   60 days.
2. DEAL-ENGINE context step: reads `outreach_threads` — which funders
   need warming (opened emails, no reply), which meetings are within
   14 days, which threads are Red.
3. HERALD synthesis: produces 8–15 ranked `ideas` rows, each with:
   `angle, house, format, rationale_chain: [signal_refs, thread_refs,
   evidence_refs], score, suggested_publisher`.
4. Monday queue: team picks from these. Accepts/rejects are outcomes
   that train the deliberation.
Agents collaborate via the blackboard (Postgres). They pass references,
not payloads. The output is recommendations with reasoning — humans
decide what the organisation says.

### 3.7 The Knowledge Wiki (LLM Wiki — Karpathy Pattern)
The wiki is the agents' memory. It compounds.

`knowledge_pages` table:
- `slug`: unique identifier (e.g. "rockefeller-foundation",
  "joseph-nganga", "ai-10bn-initiative").
- `entity_type`: funder | org | person | initiative | topic.
- `abstract` (L0, ~100 tokens): the brief card's content. Designed for
  90-second reading. The mobile dossier.
- `overview` (L1, ~2,000 tokens): the one-pager. 5-minute read.
- `body_md` (L2, full): deep intelligence with `[[wiki-links]]`.
- `confidence jsonb`: per-claim confidence (later; page-level in v1).
- `source_refs uuid[]`: which `ingest_items` contributed.
- `superseded_by`: if this page has been replaced.
- `embedding vector(1024)`: for semantic search (the index, not the
  primary store).
- `compiled_by_episode FK`: which agent run built this version.

`knowledge_page_revisions`: every edit is a logged diff with the
episode that caused it. The revision history IS the audit trail for
what the agents know and when they learned it.

**The wiki compile job (ATLAS, Celery):**
An ingest item classified as `wiki_compile` triggers ATLAS:
1. Find candidate pages (embedding search + slug match).
2. Read the existing page (L0/L1/L2 as appropriate).
3. Integrate the new information:
   - Update claims that the new source confirms or contradicts.
   - Add new intelligence.
   - Update the abstract to reflect the current state.
   - Maintain `[[wiki-links]]` (if new info mentions a known entity,
     link it).
4. If the new source contradicts a claim from a credible source →
   create a `conflicting_signal` brief in `learnings` and notify the
   relevant lead. Never resolve contradictions silently.
5. Two-source rule: claims from a single non-primary source are tagged
   `unverified` in the page body. They cannot flow into public content
   or decks.
6. Write `knowledge_page_revisions` with the full diff.

The wiki is human-readable. The team can browse it. Joseph can read
what ATLAS knows about Rockefeller before his meeting. This is why it
is better than a vector store: the knowledge is auditable.

### 3.8 Self-Learning Architecture (Three Loops)

**Loop 1: In-run self-correction.**
Every agent run: plan → act → verify against a checklist + the
eval rubric → revise if failing → submit. Circuit breakers (error rate,
gate-rejection rate, cost/output) pause the agent and page Lazarus.
This loop never writes to `playbook_versions`. It only affects the
current run.

**Loop 2: Weekly self-improvement (the reflection loop).**
Every Friday, per agent:
1. Evaluator reads the week's `episodes` joined to `outcomes`.
2. Scores against the fixed utility function / rubric.
3. Proposes ≤3 playbook diffs. Schema-enforced: every diff must cite
   ≥3 episode IDs as evidence. No evidence = no diff.
4. The full eval suite runs against the proposed playbook version.
   Any compliance-case failure → auto-reject (never reaches a human).
5. Nduta (or the agent's owner) reviews the diff in the diff-review
   UI: side-by-side diff, linked evidence episodes, eval-suite result.
6. Approved → written as `playbook_versions` vN+1. Hot-swapped
   immediately.
7. Nightly rollback watch: if utility metrics fall below the trailing
   4-week baseline for 3 consecutive days → auto-revert to vN,
   mark `rolled_back_at`, urgent notification, Learning Log entry.

**The Gödel principle:** the utility function is fixed from outside.
Agents never define what "good" means for themselves. Rubrics are
git-versioned Level-2 artifacts changed only by human PR.

**Graduation:** diff categories with 8 consecutive weeks of approvals
and measured improvement can flip to **auto-apply with sampled post-hoc
review**. Style/format heuristics graduate first. Claims-adjacent,
partner rules, and escalation rules **never graduate**. This is a
config change, not a code change — the evidence ledger exists from
Phase 2 onward.

**Loop 3: Self-healing (on failure).**
Triggered by circuit breaker trips or repeated job failures:
1. Maintenance agent queries `traces` for the failure window.
2. Root-cause analysis citing trace IDs. Schema-enforced: if no
   trace evidence exists, output is `status=insufficient_evidence`
   and the agent stops. It does not guess.
3. Fix fork:
   - Config / prompt-level → proposed as a playbook diff into Loop 2.
   - Code-level → GitHub PR with: a failing test that reproduces the
     bug, the root cause with trace links, the fix, and a risk note.
     Never auto-merged. Never to main.
4. All incidents logged in `healing_incidents`.

### 3.9 Autonomy Tiers
Every agent action class starts at T0 and earns autonomy:

| Tier | Meaning | Promotion |
|------|---------|-----------|
| T0 | Propose only; human acts | Default |
| T1 | Act internally (CRM updates, task creation); revertible | 4 wks ≥90% acceptance |
| T2 | Act externally through the gate | 4 wks T1, zero incidents |
| T3 | Act externally, statistically sampled gate | ≥98% pass rate over 8+ wks |

**Permanent T2 cap:** money/commitment claims, named partners,
political content, Tier-1/anchor funder communications.
Enforced in code against `autonomy_tiers`. Not in prompts.
Demotion automatic on incident or sustained KPI miss.

### 3.10 Compliance Architecture — The Most Important Section
The gate is the one place a bug becomes a reputational incident.

**Why these rules are existential:**
AfCEN is the infrastructure and pipeline partner to the AI $10Bn
Initiative. It does not control or hold the $10Bn. If a post says
"AfCEN has secured $10Bn for African AI" — which sounds like something
an over-enthusiastic content agent might draft — it is not just
incorrect. It is a misrepresentation to the African Development Bank,
UNDP, and any funder who has seen it. It could terminate partnerships.
The gate exists because the consequences of a failure are not
"embarrassing post" — they are "partnership termination."

**The status language rule:**
The only correct framing for the AI 10Bn Initiative is:
"The Initiative's published projections estimate a potential contribution
of up to ~$1 trillion to GDP by 2035."
Never: "The AI $10Bn Initiative will contribute $1 trillion."
Never: "We have secured $10Bn."
Never: "The Initiative has committed $3.5M to Phase I."
The gate catches the verbs and the ownership framing.

**The partner separation rule:**
WAIIS and AI 10Bn are separate initiatives with separate governance.
WAIIS content cannot mention AI 10Bn fundraising targets. AI 10Bn
content cannot mention WAIIS sponsors. A draft that accidentally
merges the two tracks can confuse both institutions and both funder
audiences. Track tags on every block and every content item; cross-
track references are a gate flag before they are a human decision.

**Joseph's override right:**
On his personal content only, Joseph can override a Pass-1 flag with
a reason, logged to audit. He is the principal. His name is on his
content. His call. But the decision is recorded — permanently — and
the reason is required.

---

## 4. The Full Data Schema

### 4.1 Core / Identity
```sql
users (
  id uuid PK,
  email unique,
  password_hash,
  full_name,
  role: admin|campaign_owner|principal|pillar_lead|member,
  pillar: energy|minerals|agribusiness|digital|cross_pillar|null,
  house: afcen|waiis|ai10bn|joseph|null,  -- default content house
  voice_profile_id FK→playbook_versions null,
  ui_preferences jsonb,  -- widget layout, theme, etc.
  google_oauth_tokens jsonb encrypted,  -- Calendar + Gmail OAuth
  created_at, updated_at
)

agents (
  id uuid PK,
  name: herald|jarvis|atlas|forge|deal_engine|deck_agent|
        evaluator|maintenance,
  status: active|paused|degraded,
  constitution_path,  -- git path, read-only
  current_playbook_version_id FK→playbook_versions,
  created_at, updated_at
)

autonomy_tiers (
  id uuid PK,
  agent_id FK,
  action_class,  -- e.g. "publish_post", "send_email", "score_contact"
  tier: t0|t1|t2|t3,
  cap: t2_permanent bool,  -- if true, never promotes past T2
  since,
  evidence_episode_ids uuid[],
  created_at, updated_at
)

diff_categories (
  id uuid PK,
  agent_id FK,
  category_name,  -- e.g. "style_format", "search_strategy",
                  -- "scoring_weights", "claims_adjacent"
  auto_apply_eligible bool default false,
  weeks_of_evidence int,
  last_evaluated,
  created_at, updated_at
)
```

### 4.2 Ingestion
```sql
ingest_items (
  id uuid PK,
  source_type: rss|scrape|grant_portal|social_engagement|
               analytics|webhook|email_inbound,
  source_id,  -- e.g. "afdb_newsroom", "firecrawl_crawl_xyz"
  fetched_at,
  payload jsonb,
  dedupe_key unique,
  decision: stored|duplicate|escalated|queued|discarded,
  route: wiki_compile|grant_candidate|engagement_signal|
         analytics|escalate_conflicting|discard_low_trust|null,
  decided_at,
  embedding vector(1024),
  created_at
)

monitored_sources (
  id uuid PK,
  name,
  kind: news_page|news_search|grant_portal|site_crawl|rss,
  config jsonb,  -- url, query, include_paths, schedule, etc.
  credits_budget_per_run int,
  active bool,
  last_run,
  last_success,
  created_at, updated_at
)

source_ledger (
  id uuid PK,
  domain,
  category: multilateral|government|primary_research|wire_service|
            aggregator|seo_farm|social,
  trust_score float,  -- 0.0–1.0
  pinned bool,  -- pinned sources never auto-adjusted below a floor
  last_adjusted,
  adjustment_history jsonb[],
  created_at, updated_at
)
```

### 4.3 Knowledge Wiki
```sql
knowledge_pages (
  id uuid PK,
  slug unique,
  entity_type: funder|org|person|initiative|topic,
  title,
  abstract text,     -- L0: ~100 tokens, mobile brief
  overview text,     -- L1: ~2,000 tokens, one-pager
  body_md text,      -- L2: full, with [[wiki-links]]
  confidence jsonb,  -- {overall: 0.0-1.0, last_confirmed: date}
  source_refs uuid[],  -- FK→ingest_items[]
  unverified_claims text[],  -- claims with only one non-primary source
  superseded_by uuid null FK→knowledge_pages,
  embedding vector(1024),
  compiled_by_episode_id FK→episodes null,
  created_at, updated_at
)

knowledge_page_revisions (
  id uuid PK,
  page_id FK→knowledge_pages,
  diff text,       -- unified diff format
  summary text,    -- one-sentence description of what changed
  reason: wiki_compile|manual_edit|conflict_resolution,
  episode_id FK→episodes null,
  revised_by_id FK→users null,
  created_at      -- append-only
)
```

### 4.4 Agents / Learning
```sql
episodes (
  id uuid PK,
  agent_id FK,
  workflow_name,
  input_ref jsonb,   -- reference to input (not the input itself)
  output_ref jsonb,  -- reference to output
  tool_calls jsonb[],
  prompt_tokens int,
  completion_tokens int,
  cost_usd float,
  duration_ms int,
  self_check_passed bool,
  self_check_notes text,
  gate_verdict: pass|flag|block|null,
  gate_id uuid null,
  eval_run bool default false,
  trace_id uuid,
  playbook_version_id FK,
  created_at        -- append-only
)

traces (
  id uuid PK,
  trace_id,
  span_id,
  parent_span_id null,
  operation_name,
  attributes jsonb,
  status: ok|error|timeout,
  start_at,
  end_at,
  created_at        -- append-only
)

outcomes (
  id uuid PK,
  episode_id FK,
  outcome_type: approval|rejection|edit|engagement|reply|
                meeting|advance|conversion|no_response,
  value jsonb,      -- metric value (engagement rate, reply bool, etc.)
  decided_by_id FK→users null,
  note text,
  created_at        -- append-only
)

playbook_versions (
  id uuid PK,
  agent_id FK,        -- null if scope=user
  user_id FK null,    -- non-null for voice profiles
  scope: agent|user,
  version int,
  full_text text,
  diff_from_previous text,
  diff_category,
  evidence_episode_ids uuid[],  -- ≥3 required for agent diffs
  expected_effect text,
  metric_to_watch,
  eval_run_id FK→eval_runs null,
  approver_id FK→users null,
  auto_applied bool default false,
  applied_at,
  rolled_back_at null,
  rollback_reason text null,
  created_at, updated_at
)

eval_cases (
  id uuid PK,
  agent_id FK,
  category: compliance|quality|calibration,
  mode: hard_assertion|llm_judge|trace_assertion,
  input_fixture jsonb,
  expected jsonb,
  rubric_path text null,  -- git path for llm_judge rubrics
  weight float default 1.0,
  source_episode_id FK null,  -- if created from an incident
  created_at, updated_at
)

eval_runs (
  id uuid PK,
  playbook_version_id FK,
  triggered_by: reflection|manual|ci,
  results jsonb[],  -- {case_id, passed, score, notes}[]
  overall_pass bool,
  run_at
)

learnings (
  id uuid PK,
  agent_id FK null,
  week_ending date,
  memo_md text,         -- the weekly reflection memo
  diffs_proposed int,
  diffs_approved int,
  diffs_rejected int,
  utility_score float,
  conflict_signal bool, -- true if a conflicting-signal brief
  embedding vector(1024),
  created_at
)

healing_incidents (
  id uuid PK,
  agent_id FK,
  triggered_by: circuit_breaker|repeated_failure|manual,
  trace_ids uuid[],
  root_cause_md text,
  fix_type: config|prompt|code_pr,
  pr_url text null,
  status: investigating|fix_proposed|resolved|insufficient_evidence,
  resolved_at null,
  created_at, updated_at
)
```

### 4.5 Compliance Gate
```sql
gate_checks (
  id uuid PK,
  content_text text,
  content_type: post|email|deck|newsletter|brief|talking_points,
  track: core|programs|waiis|ai10bn|joseph_personal,
  author_id FK→users,
  signed_source_ref text null,
  pass1_verdict: pass|flag|block,
  pass1_findings jsonb[],  -- {rule, match, span, route_to}[]
  pass2_verdict: pass|flag|block|skipped,
  pass2_findings jsonb[],
  combined_verdict: pass|flag|block,
  route_to: none|lead|nduta|joseph|kandeh|hard_stop,
  gate_id uuid unique,     -- the ID the publishing pipeline checks
  created_at               -- append-only
)

approvals (
  id uuid PK,
  gate_id FK→gate_checks,
  content_ref jsonb,
  route_to,
  status: pending|approved|edited|rejected|override,
  decided_by_id FK→users null,
  decided_at null,
  edit_text text null,     -- if edited
  override_reason text null,  -- if overridden (Joseph only)
  created_at, updated_at
)
```

### 4.6 Content
```sql
content_intake (
  id uuid PK,
  external_id,             -- Google Sheet row ID
  submitted_by_id FK→users null,
  pillar_theme,
  angle text,
  proof_point text,
  proof_status: confirmed|tbd|needs_verification,
  target_audience,
  sensitivity: public_safe|partner_only|private_hold|confidential,
  channel_targets jsonb[],  -- parsed: {platform, account, companion?}
  campaign,
  house: afcen|waiis|ai10bn|joseph_personal,
  priority: high|medium|low,
  status: idea|accepted|drafting|in_review|approved|scheduled|
          published|archived|blocked|held,
  owner_id FK→users null,
  target_publish_date date null,
  notes_raw text,
  unblock_conditions jsonb[],  -- {type, description, owner_id, status}
  reference_links text[],      -- Google Docs links (human-read only)
  row_hash,                    -- for change detection on sync
  sheet_synced_at,
  created_at, updated_at
)

content_items (
  id uuid PK,
  intake_id FK→content_intake null,
  idea_id FK→ideas null,
  house,
  channel,
  account,          -- which account (joseph_personal, afcen_page, etc.)
  format: post|article|thread|carousel|newsletter_section|brief,
  body_draft text,
  body_final text,
  gate_id FK→gate_checks null,
  approval_id FK→approvals null,
  status: draft|in_review|approved|scheduled|published|archived,
  scheduled_at null,
  published_at null,
  platform_post_id text null,  -- returned by the publishing platform
  owner_id FK→users,
  episode_id FK null,
  performance jsonb,   -- impressions, engagements, clicks, etc.
  created_at, updated_at
)

ideas (
  id uuid PK,
  source: deliberation|curation|joseph_request|team_submission|
          intake_sheet|rapid_response,
  house,
  angle text,
  format,
  rationale_chain jsonb,  -- {signal_refs[], thread_refs[], evidence_refs[]}
  score float,
  suggested_publisher_id FK→users null,
  status: proposed|accepted|rejected|drafted|archived,
  decided_by_id FK→users null,
  week_of date,
  episode_id FK null,
  created_at, updated_at
)
```

### 4.7 CRM / Outreach
```sql
organizations (
  id uuid PK,
  name,
  type: funder|bilateral|dfi|corporate|partner|government,
  track_tags: core|programs|waiis|ai10bn []  -- multi-track allowed
  tier: tier1_anchor|tier2_warm|tier3_cold,
  wiki_page_id FK→knowledge_pages null,
  website,
  linkedin_url,
  notes text,
  created_at, updated_at
)

contacts (
  id uuid PK,
  org_id FK,
  full_name,
  role,
  seniority: c_suite|vp|director|manager|analyst,
  email null,
  linkedin_url null,
  phone null,
  warmth_source: direct_relationship|warm_intro|conference|cold,
  consent_flags jsonb,  -- email_ok, linkedin_ok, etc.
  last_known_position,
  last_verified date,
  wiki_page_id FK→knowledge_pages null,
  created_at, updated_at
)

outreach_threads (
  id uuid PK,
  org_id FK,
  primary_contact_id FK→contacts null,
  track: core|programs|waiis|ai10bn,
  owner_id FK→users,
  backstop_id FK→users,
  stage: targeted|engaged|proposal_sent|in_discussion|
         committed|contracted|closed,
  warmth: cold|warm|hot,
  score float,
  quintile int,       -- 1–5, persisted at scoring time, immutable
  next_action text,
  next_action_due date null,
  traffic_light: green|amber|red,
  dossier_id FK→dossiers null,
  data_room_url text null,
  restricted bool default false,
  last_touch,
  last_touch_channel,
  created_at, updated_at
)

activities (
  id uuid PK,
  thread_id FK,
  activity_type: email_sent|email_reply|call|meeting|note|
                 deck_sent|deck_opened|data_room_viewed|
                 linkedin_message|whatsapp|intro_made|
                 commitment_recorded|stage_advanced,
  actor_type: human|agent,
  actor_id FK→users null,
  agent_id FK→agents null,
  content_ref jsonb,     -- email body ref, note text, etc.
  episode_id FK null,
  created_at             -- append-only
)

tasks (
  id uuid PK,
  thread_id FK null,
  owner_id FK→users,
  type: send_email|make_call|linkedin_task|whatsapp_task|
        capture_meeting|review_deck|confirm_commitment|
        close_unblock_condition,
  status: open|completed|dismissed,
  due date null,
  drafted_content text null,  -- pre-drafted by an agent, human edits+sends
  gate_id FK null,
  episode_id FK null,
  created_at, updated_at
)

sequences (
  id uuid PK,
  thread_id FK,
  template_name,
  status: active|paused|completed|cancelled,
  current_step int default 0,
  created_at, updated_at
)

sequence_steps (
  id uuid PK,
  sequence_id FK,
  step_number int,
  channel: email|linkedin_task|whatsapp_task|call_task,
  delay_days int,
  template_ref,
  status: pending|sent|skipped|failed,
  sent_at null,
  created_at, updated_at
)

dossiers (
  id uuid PK,
  thread_id FK,
  version int,
  abstract text,   -- L0: mobile brief (≤300 words)
  overview text,   -- L1: one-pager
  full_md text,    -- L2: deep intelligence
  hook_by_track jsonb,   -- {core: str, ai10bn: str, waiis: str, ...}
  red_flags text[],
  warm_paths jsonb[],    -- {description, confidence, via_contact_id?}
  comparable_deals jsonb[],
  source_refs uuid[],
  confidence float,
  compiled_episode_id FK,
  expires_at,      -- dossier freshness; triggers refresh when past
  created_at, updated_at
)

calendar_events (
  id uuid PK,
  google_event_id unique,
  user_id FK→users,
  title,
  start_at,
  end_at,
  attendees_raw jsonb,
  linked_thread_id FK→outreach_threads null,
  briefing_status: none|briefed|captured,
  created_at, updated_at
)
```

### 4.8 Decks
```sql
blocks (
  id uuid PK,
  type: claim|stat|bio|case_study|precedent|governance|ask|
        pillar_description|team|closing|progress_update,
  track_tags text[],     -- which tracks can use this block
  audience_types text[], -- which skeletons can include this block
  sensitivity: public_safe|partner_only|confidential,
  confirmation_status: confirmed|unconfirmed|needs_review,
  content_md text,
  source_ref text null,  -- citation for claims/stats
  owner_id FK→users,
  version int,
  superseded_by uuid null FK→blocks,
  created_at, updated_at
)

deck_templates (
  id uuid PK,
  name,
  house: afcen|waiis|ai10bn,
  audience_type: philanthropy_anchor|bilateral_ta|corporate_sponsor|
                 dfi|principal_brief,
  skeleton_json jsonb,   -- slide_order[], per-slot accepted_block_types
  slides_master_id,      -- Google Slides template file ID
  active bool,
  created_at, updated_at
)

deck_registry (
  id uuid PK,
  thread_id FK,
  template_id FK→deck_templates,
  block_versions jsonb,  -- {block_id: version} snapshot at assembly time
  presenter_id FK→users,
  gate_id FK→gate_checks null,
  slides_url text,
  slides_id text,        -- Google Slides file ID for edit operations
  status: assembling|draft|flagged|sent|superseded,
  assembly_episode_id FK,
  sent_at null,
  created_at, updated_at
)
```

### 4.9 Grants
```sql
grants (
  id uuid PK,
  funder_org_id FK→organizations null,
  funder_name,           -- denormalised for unmatched funders
  programme_name,
  deadline date null,
  amount_range text null,
  eligibility_notes text,
  fit_by_track jsonb,    -- {track: fit_rationale}
  status: identified|pursuing|applied|awarded|declined|expired,
  owner_id FK→users null,
  thread_id FK→outreach_threads null,  -- if pursuing
  source_ingest_id FK→ingest_items,
  created_at, updated_at
)
```

### 4.10 Notifications
```sql
notifications (
  id uuid PK,
  user_id FK→users,
  type: escalation|sla_nudge|opportunity_push|rhythm|
        system_alert|circuit_breaker,
  urgency: now|today|this_week,
  title,
  body text,
  action_payload jsonb,  -- inline action data (approve/snooze/assign)
  action_taken text null,
  read_at null,
  acted_at null,
  delivery_channel: in_app|email|both,
  sent_via_email bool default false,
  created_at             -- append-only
)
```

### 4.11 WAIIS (Phase 3)
```sql
summit_registrations (
  id uuid PK,
  contact_id FK→contacts null,
  name,        -- denormalised for guests without contact records
  track: state|investor,
  wave int,
  status: invited|confirmed|arrived|cancelled,
  curation_review_by_id FK→users null,
  logistics jsonb,  -- arrival, visa, dietary, badge
  badge_qr text null,
  created_at, updated_at
)

summit_sessions (
  id uuid PK,
  pillar: energy|minerals|agribusiness|digital|plenary,
  title,
  slot_start,
  slot_end,
  room,
  created_at, updated_at
)

session_speakers (  -- junction
  session_id FK, speaker_id FK, role: speaker|moderator|panelist
)

speakers (
  id uuid PK,
  contact_id FK→contacts,
  bio_block_id FK→blocks null,
  briefing_status: not_started|pack_sent|confirmed,
  protocol_notes text,
  handler_id FK→users null,
  travel jsonb,
  created_at, updated_at
)

sponsors (
  id uuid PK,
  org_id FK→organizations,
  tier: strategic|pillar|convening|corporate_star,
  pillar text null,
  benefits_schedule jsonb,
  status: targeted|engaged|proposal|committed|contracted,
  created_at, updated_at
)

sponsor_fulfillments (
  id uuid PK,
  sponsor_id FK,
  benefit_description text,
  owner_id FK→users,
  due date,
  status: pending|delivered,
  created_at, updated_at
)

deal_instruments (
  id uuid PK,
  pillar,
  parties text[],  -- org IDs or names (encrypted if confidential)
  instrument_type,
  status: pipeline|negotiated|signed|announced,
  value_encrypted text null,  -- encrypted at rest until announced
  announcement_ref uuid null FK→gate_checks,
  created_at, updated_at
)

commitments (
  id uuid PK,
  source: communique|session|instrument|debrief,
  description text,
  owner_id FK→users null,
  due date null,
  status: candidate|confirmed|in_progress|delivered|lapsed,
  instrument_id FK→deal_instruments null,
  created_at, updated_at
)
```

---

## 5. The Agents in Detail

### 5.1 HERALD — Content Engine

**Constitution (frozen):**
- Never claim AfCEN controls or holds Initiative capital.
- Never use "secured / committed / funded / approved / signed /
  confirmed" for unverified states.
- All economic projections attributed to the source: "the Initiative's
  published projections estimate…"
- Never reference confidential keywords.
- Track separation: WAIIS content does not mention AI 10Bn; AI 10Bn
  does not mention WAIIS sponsors.
- Partner-separation: AfCEN is the infrastructure and pipeline partner.
  Never the steward of the $10Bn.

**Playbook (versioned — what HERALD learns):**
- Voice rules per house (AfCEN: data-led, assertive, African-
  development expertise; WAIIS: political gravitas, deal-momentum;
  AI 10Bn: TA/philanthropy framing, SE4ALL precedent; Joseph personal:
  direct, no hedging, bold assertions, signature moves).
- Hook patterns per audience (philanthropies vs. DFIs vs. tech
  ecosystem vs. governments).
- Format heuristics (length by channel and house; carousel vs. single;
  when to use a statistic opener).
- Banned phrases per house.
- What Joseph edits (trained from his corrections).

**Tools:**
- Read `knowledge_pages` (wiki-first before any web call).
- Read `content_intake` (for the item's framing and constraints).
- Read `ideas` (for the deliberation rationale chain).
- Read `content_items` (recent performance by format and house).
- Call `gate/pass1` as a pre-check before submitting a draft.
- Write `content_items` (drafts).
- Write `episodes` (every run).

**OKRs:**
- Gate first-pass rate ≥95%.
- Engagement +15% QoQ per house.
- ≥30% of new contacts in the CRM attributable to content.
- Lead acceptance ≥85% (topic leads accept drafts without major edits).
- Cost per published asset trending down.

### 5.2 JARVIS — Assembly Engine
Assembles the Nexus Brief and long-form documents from section drafts.
Coordinates with HERALD for section drafts. Manages Ghost publication.
Handles the "From Joseph's desk" section — drafts in Joseph's voice,
puts it in his approval queue Thursday morning.

**OKRs:**
- Nexus Brief published every Thursday without manual intervention.
- "From Joseph's desk" section accepted by Joseph ≥80% of the time
  without major edits.

### 5.3 ATLAS — Research & Intelligence

**Constitution (frozen):**
- Wiki first. Check `knowledge_pages` before any web call.
  If the wiki answer is fresh (L0 <7 days, L1 <14 days, L2 <21 days
  for the query type), serve from wiki. No Firecrawl call.
- Source ledger trust enforced: claims from low-trust sources are
  tagged `unverified` and cannot be used in public content or decks.
- Two-source rule: every claim that will flow into public content
  or a funder document needs two independent sources or one primary.
- Contradiction rule: if a new source contradicts a wiki claim from
  a credible source, escalate as a conflicting-signal brief. Never
  resolve silently.
- High-stakes anomaly rule: a credible signal about a funder's
  strategy shift escalates to Joseph even if unconfirmed. Tag as
  "unverified, high-relevance."

**Playbook (versioned — what ATLAS learns):**
- Which search strategies produce high-trust, relevant results for
  funder research.
- How to scope subagent tasks for efficiency (what scope definition
  produces useful outputs with minimal Firecrawl credit spend).
- Source quality patterns (which domains reliably produce citable
  intelligence for African development funders).

**Tools:**
- Read/write `knowledge_pages` and `knowledge_page_revisions`.
- Read `ingest_items` (routed wiki_compile items).
- Firecrawl v2 (self-hosted): scrape, crawl, search (with probe flags).
- Tavily/Brave API (fallback when Firecrawl search unavailable).
- World Bank, IMF, AfDB documents APIs (primary sources, called
  directly, not through Firecrawl).
- Write `dossiers`.
- Spawn subagent tasks (via Celery, per the orchestrator-worker pattern).
- Write `learnings` (weekly memos).
- Write `episodes` and `traces`.

**OKRs:**
- ≥90% of grant alerts rated "worth pursuing" by the team.
- Zero missed grant deadlines on monitored funds.
- Dossier briefs cited in ≥70% of outreach proposals.
- Breaking-news signal surfaced within 2 hours.
- Flagged-claim error rate <5%.

**Effort scaling rules (code-enforced, not prompt-based):**
```python
def should_spawn_subagents(request_tier, wiki_freshness, meeting_days):
    if request_tier == "l0" and wiki_freshness < 7 and not meeting_days:
        return False  # serve from wiki
    if request_tier == "l0" and meeting_days and meeting_days <= 5:
        return ["org_strategy", "principals"]  # targeted refresh
    if request_tier in ("l1", "l2"):
        return ALL_SUBAGENTS
    return False
```

### 5.4 FORGE — Grant Intelligence
Watches `monitored_sources` of type `grant_portal`. Receives Firecrawl
crawl results. Extracts: funder, programme, deadline, amount range,
eligibility. Matches against the four tracks. Scores fit. Creates
`grants` rows. Schedules deadline alerts (T-30/14/7/3/1 days).

**OKRs:**
- ≥90% precision on grant alerts (team rates them "worth pursuing").
- Zero missed deadlines on monitored programmes.

### 5.5 DEAL-ENGINE — Pipeline Scoring

**Constitution (frozen):**
- Never recommend reaching out to a contact marked `restricted` without
  explicit owner approval.
- Never recommend an approach channel that contradicts a contact's
  consent flags.
- Warmth estimates are estimates; always surface uncertainty.

**Playbook (versioned — what DEAL-ENGINE learns):**
- Scoring weights (which signals predict reply/meeting/advance).
  Weights live in the playbook — when the reflection loop proposes
  a weight adjustment backed by calibration evidence, Nduta approves
  the diff and the new weights are live immediately.
- Recommended next-action heuristics per stage and warmth.

**OKRs:**
- Calibration: top-quintile threads advance at ≥3× the rate of bottom-
  quintile threads. If they don't, the scoring is decoration — the
  calibration chart shows this warning plainly.
- 100% of active threads carry a live next action and due date.
- Zero Red threads older than 7 days without escalation to Nduta.

**Scoring model (initial weights in the playbook):**
```
score = (
  warmth_source       × 0.25  # direct_relationship=1.0, warm_intro=0.7,
  +                           # conference=0.4, cold=0.1
  seniority           × 0.20  # c_suite=1.0, vp=0.8, director=0.6, ...
  +
  org_fit_by_track    × 0.20  # 0.0–1.0 from ATLAS track-match score
  +
  engagement_recency  × 0.15  # days since last positive signal (decay)
  +
  engagement_frequency× 0.10  # number of positive signals (saturates)
  +
  intro_path_quality  × 0.10  # known_warm_path=1.0, none=0.0
)
```
This is the initial model. The reflection loop tunes the weights.

### 5.6 Deck Agent

**Constitution (frozen):**
- Never assemble a deck with a block whose `confirmation_status` is
  not `confirmed`.
- Never use a block whose `track_tags` do not include the thread's
  track. Cross-track is a hard error (`DeckAssemblyError`), not a flag.
- Never apply Joseph's voice profile to approved block content. Voice
  applies only to the generated personalization layer.
- Never auto-send a deck. Decks are always proposed to a human first.

**Playbook (versioned — what the deck agent learns):**
- Block selection heuristics (which blocks in which positions correlate
  with meetings scheduled).
- Personalization vocabulary mappings per funder type.
- Skeleton ordering patterns (what slide sequences Joseph edits, and
  what the successful sequences look like).

**OKRs:**
- Request to review-ready ≤20 minutes.
- 100% of claims traceable to a confirmed block or an ATLAS-sourced
  dossier citation.
- Deck-variant-to-meeting conversion rate improving quarter-over-quarter.

### 5.7 Evaluator

The evaluator is a meta-agent that reads other agents' episode logs
and proposes improvements. It does not execute tasks. It observes,
scores, and recommends.

**Constitution (frozen):**
- The evaluator's rubrics (stored in `agents/rubrics/`, git-versioned)
  are Level-2 artifacts. The evaluator may not propose changes to its
  own rubrics. Rubric changes require a human PR.
- Diffs that would modify a constitution are automatically rejected.
  Constitutions are out of scope for the evaluator.
- Claims-adjacent diff categories are out of scope for auto-apply,
  regardless of evidence.

**Weekly reflection task:**
```
For each agent:
1. Load episodes from the past 7 days.
2. Load outcomes joined to those episodes.
3. Score each episode against the agent's rubric (0–1 scale).
4. Identify patterns in the bottom-scoring episodes.
5. Propose ≤3 playbook diffs, each citing ≥3 episode IDs.
6. Write a learnings memo regardless of whether diffs were proposed.
```

### 5.8 Maintenance Agent

**Constitution (frozen):**
- Never make changes to main without a human-reviewed PR.
- Never apply a fix without trace evidence. If traces are
  insufficient: `status=insufficient_evidence`, stop, report.
- Config fixes go through the reflection pipeline (Loop 2).
  Code fixes go as PRs. Never directly applied.

**Circuit breaker triggers:**
- Error rate >10% in any 1-hour window for any agent.
- Gate-rejection rate >20% in any 24-hour window.
- Cost/output >3× the 30-day rolling average.
- Celery beat missed schedule >2× in any day.

---

## 6. The Integrations (In-Process, No n8n)

### 6.1 Google Calendar
`apps/integrations/google_calendar.py`

**OAuth2 per user.** Scopes: `calendar.readonly` (Phase 2B). Joseph's
account is the first connected; team accounts in Phase 2C.

**Celery beat (every 5 min):** `sync_calendar_events(user_id)`
- Fetch events from Google Calendar API (`events.list`, `timeMin=now`,
  `timeMax=now+30days`).
- Upsert into `calendar_events` by `google_event_id`.
- For new events: fuzzy-match title and attendees against
  `organizations` and `contacts`. Confidence >90% → auto-link
  with a notification for confirmation. Confidence 50–90% →
  linkage suggestion in Joseph's action queue. <50% → no action.

**Django webhook view:** `POST /webhooks/google/calendar/`
- Receives Google Calendar push notifications.
- Triggers `sync_calendar_events` immediately (Celery task).
- Returns 200 within 200ms.

**Pre-meeting flow triggers (Celery task: `check_meeting_prep`):**
```
Daily, per linked calendar event:
  T-5 days: trigger dossier refresh + deck proposal
  T-2 days: push L0 brief to Joseph's mobile notification
  T-1 day: draft talking points (3 bullets per track from dossier)
  T-0 (8am): cache L0 brief in service worker
  T+0 (meeting end): send capture prompt notification
```

### 6.2 Gmail
`apps/integrations/gmail.py`

**OAuth2 per connected mailbox.** Scopes: `gmail.send`,
`gmail.readonly`, `gmail.modify`.

**Celery beat (every 10 min):** `sync_gmail_inbox(mailbox_id)`
- `users.history.list` with `historyId` cursor (efficient, not full
  scan).
- New messages → parse headers (from, to, subject, references,
  in_reply_to) → attempt thread matching by email domain + subject.
- Matched → create `activity` (type: email_reply) + triage queue item.
- Unmatched → general inbox review queue.

**Django webhook view:** `POST /webhooks/google/gmail/`
- Gmail push notification (via Cloud Pub/Sub or direct watch).
- Triggers `sync_gmail_inbox` immediately.

**Email sending (via EmailSender interface):**
```python
class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str,
             thread_id: str | None, mailbox_id: str) -> str: ...

class GmailEmailSender:
    # Uses Gmail API messages.send with In-Reply-To header
    # Enforces: daily_cap, ramp_up_schedule, suppression_check
    # Raises: CapExceeded, AddressSuppressed

class InstantlyEmailSender:
    # Fallback for scale; same interface
```

**Deliverability guardrails (enforced in the adapter, not views):**
- Daily cap: 50 sends/mailbox/day (configurable; ramp-up for new
  mailboxes: week 1: 20, week 2: 35, week 3: 50).
- Suppression check: raises `AddressSuppressed` if the recipient is
  on the suppression list. Not a warning — a raised exception.
- Every send creates an `activity` row (append-only audit).
- Unsubscribe header and footer on every sequence email (legal baseline
  for GDPR/CAN-SPAM).

### 6.3 Google Sheets
`apps/integrations/google_sheets.py`

**Service account** (read + optional write).

**Celery beat (every 15 min):** `sync_content_intake_sheet()`
- Read the intake sheet via Sheets API.
- Row-hash change detection (only process changed rows).
- Parse and normalize every field (sensitivity, channels, status,
  unblock conditions — all per TA.1 rules).
- Upsert `content_intake` by `external_id`.
- Parse failures → review queue notification, never silent drop.
- Optional write-back: status, owner updated from Campaign OS → sheet
  (config flag; off by default; enabled only after team migration).
- Skip rows marked EXAMPLE or with no content.

### 6.4 Firecrawl
`apps/ingestion/firecrawl.py`

**Self-hosted on Azure Container Apps:**
- Base URL: `https://firecrawl-api.kindplant-70384d25.southafricanorth.azurecontainerapps.io`
- Path prefix: `/v2`
- Auth: `Authorization: Bearer {FIRECRAWL_API_KEY}` (rotate from
  default `fc-selfhosted` immediately).

**Capability probe (on Django startup, result in `settings.FIRECRAWL_CAPS`):**
```python
FIRECRAWL_CAPS = probe_firecrawl_capabilities()
# {
#   "scrape": True,
#   "change_tracking": True|False,
#   "search": True|False,      # needs SearXNG or SERP key
#   "crawl_webhooks": True|False,
#   "structured_extraction": "json_format"|"agent"|None,
#   "pdf_parse": True|False
# }
```
Every Firecrawl call checks the capability flag before executing.
If a capability is absent, the job uses the fallback or logs
`insufficient_capability` and skips gracefully.

**Monitored sources job (Celery beat, per source schedule):**
```
news_page    → /v2/scrape (markdown, changeTracking if available)
               → ingest_item if content changed
news_search  → /v2/search if search cap, else Tavily/Brave fallback
               → each result → ingest_item
grant_portal → /v2/crawl (include_paths, webhook delivery if available,
               else poll) → each page → ingest_item
rss          → feedparser (no Firecrawl needed for RSS)
               → each item → ingest_item
```

**Webhook callback:** `POST /webhooks/firecrawl/crawl/{job_id}/`
- Receives completed crawl pages.
- Validates HMAC.
- For each page → creates `ingest_item` → queues `route_ingest_item`.
- Returns 200 within 100ms.

**ATLAS subagent tool (within dossier compilation):**
```python
@atlas_tool
def scrape_page(url: str, schema: dict | None = None) -> str:
    # Uses /v2/scrape with JSON format if schema provided
    # Falls back to markdown if not
    # Credits logged to dossier episode
    # Respects source budget: raises BudgetExceeded after 8 pages

@atlas_tool
def search_web(query: str) -> list[SearchResult]:
    # Uses /v2/search if FIRECRAWL_CAPS["search"]
    # Falls back to Tavily/Brave
```

### 6.5 Google Slides
`apps/integrations/google_slides.py`

**Service account** with Slides + Drive scope.

**Key operations:**
```python
def copy_template(template_file_id: str, title: str) -> str:
    # Drive API: files.copy → returns new file ID

def batch_update(file_id: str, requests: list[dict]) -> None:
    # Slides API: presentations.batchUpdate
    # Used for: replaceAllText, insertImage, updateTableCellProperties

def export_as_pdf(file_id: str) -> bytes:
    # Drive API: files.export (PDF)
    # Used for offline fallback on mobile
```

**Named placeholder convention (in slide masters):**
`{{BLOCK_CLAIM_1}}`, `{{ASK_AMOUNT}}`, `{{FUNDER_HOOK}}`,
`{{PRESENTER_NAME}}`, `{{DATE}}` — consistent naming across all
house masters so the assembly algorithm is house-agnostic.

### 6.6 DocSend / Google Drive
**Webhook views:**
`POST /webhooks/docsend/` — DocSend link visit events.
`POST /webhooks/drive/` — Drive sharing/view events.

Both validated by HMAC. Both create `activity` rows
(type: `data_room_viewed`) against the matched thread. Both return
200 immediately. Processing is async (Celery: `process_data_room_event`).

**Deal signal job (Celery, triggered by each new event):**
- 3+ events on the same document in 48h → opportunity notification.
- Time on page >2× the average for that document type → intelligence
  note on the thread.
- First open after ≥7 days of silence → "finally opened" notification.

---

## 7. The Publishing Pipeline (Inherited From Fork)

The AfCEN Platform fork (BrightBean, rebranded Campaign OS) handles
first-party social publishing. The gate hook is patched into its
publish task.

**Gate hook (untouchable):**
```python
# In the fork's publish task, before any platform API call:
def publish_post(post_obj):
    gate_result = verify_gate_id(post_obj.gate_id)
    if not gate_result.valid:
        raise GateVerificationFailed(
            f"Post {post_obj.id} has no valid gate clearance. "
            f"gate_id={post_obj.gate_id}"
        )
    if gate_result.content_hash != hash(post_obj.body):
        raise GateVerificationFailed(
            f"Post body has changed since gate clearance. "
            f"Resubmit for gate check."
        )
    # proceed to platform API
```

**`/gate/verify/{gate_id}/` endpoint (Django view):**
Returns: `{valid: bool, verdict: str, content_hash: str}`.
Used by the gate hook above and by the mobile approval link renderer
to confirm a gate result is still valid before presenting approve/reject
to Joseph.

---

## 8. The Mobile Experience (Complete Spec)

Every screen that Joseph uses on mobile must meet:
- 375px viewport (iPhone SE / mid-range Android).
- 3-second load on a 3G connection (LCP ≤ 3s on Lighthouse throttled).
- Offline capability for the key read paths (service worker cache).
- One-tap primary action per screen.
- No horizontal scroll.
- Magic-link capable: notification deep-links open the relevant action
  without requiring a full login flow (session cookie check; if valid,
  skip auth; if not, magic-link login).

**Joseph's mobile home (`/joseph/` — role-gated):**

```
┌─────────────────────────────────┐
│  ☀ Good morning, Joseph          │
│  Sunday, 14 June · Nairobi       │
├─────────────────────────────────┤
│  TODAY'S MEETINGS                │
│                                  │
│  ┌──────────────────────────┐   │
│  │ Rockefeller Foundation   │   │
│  │ 2:00 PM · Lunch meeting  │   │
│  │                          │   │
│  │ [Brief] [Deck] [Capture] │   │
│  └──────────────────────────┘   │
│                                  │
│  ┌──────────────────────────┐   │
│  │ GIZ Germany              │   │
│  │ 4:30 PM · Video call     │   │
│  │                          │   │
│  │ [Brief] [Deck] [Capture] │   │
│  └──────────────────────────┘   │
├─────────────────────────────────┤
│  ACTION QUEUE (4)                │
│                                  │
│  🔴 Gate escalation — AI 10Bn   │
│     "committed" flagged          │
│     [View] [Approve] [Reject]    │
│                                  │
│  📋 Deck review — Schmidt Futures│
│     Philanthropy anchor, 12 slides│
│     [Review]                     │
│                                  │
│  ... 2 more                      │
├─────────────────────────────────┤
│  RED THREADS                     │
│  Schmidt Futures · 11 days silent│
│  [View thread]                   │
└─────────────────────────────────┘
```

**Brief card (tapping [Brief] on a meeting):**
```
┌─────────────────────────────────┐
│  ← Rockefeller Foundation       │
│                                  │
│  WHO                             │
│  Sarah Chen, VP Africa Programs  │
│                                  │
│  WHY NOW                         │
│  They committed $40M to DPI in   │
│  East Africa last month. Our     │
│  Secretariat pitch maps directly │
│  onto their stated thesis.       │
│                                  │
│  HOOK (AI 10Bn)                  │
│  "The Secretariat is the         │
│  operational engine for your     │
│  existing DPI investment thesis — │
│  not a new bet, a multiplier."   │
│                                  │
│  RED FLAGS                       │
│  • SE4ALL figure unconfirmed     │
│    (do not cite until Will       │
│    confirms)                     │
│  • Previous conversation (2024)  │
│    mentioned capacity concerns — │
│    address the team slide        │
│                                  │
│  WARM PATH                       │
│  Dr. Amina via Mission 300 (she  │
│  knows Sarah directly)           │
│                                  │
│  ──────────────────────────────  │
│  Compiled 2h ago · 6 sources     │
│  [Full intelligence →]           │
└─────────────────────────────────┘
```

**Post-meeting capture screen:**
```
┌─────────────────────────────────┐
│  ← Capture: Rockefeller          │
│                                  │
│  Just finished your meeting.     │
│  Capture now while it's fresh.   │
│                                  │
│  ┌──────────────────────────┐   │
│  │  🎙 Hold to record voice  │   │
│  │     note                 │   │
│  └──────────────────────────┘   │
│                                  │
│  ─── or fill the quick form ───  │
│                                  │
│  Commitments made?               │
│  ┌──────────────────────────┐   │
│  │ (free text)              │   │
│  └──────────────────────────┘   │
│                                  │
│  Next step:                      │
│  ┌──────────────────────────┐   │
│  │ (free text)              │   │
│  └──────────────────────────┘   │
│                                  │
│  Follow-up due:  [date picker]   │
│  Warmth: [Warmer] [Same] [Cooler]│
│                                  │
│  [Save and continue]             │
│  [Remind me in 2 hours]          │
└─────────────────────────────────┘
```

**Magic-link approval screen (works from any notification link):**
```
┌─────────────────────────────────┐
│  Campaign OS · Approval Request  │
│                                  │
│  GATE FINDING                    │
│  Rule: status_language           │
│  Flagged: "committed to Phase I" │
│  Track: AI 10Bn                  │
│  Author: Dennis                  │
│                                  │
│  DRAFT (scroll)                  │
│  ┌──────────────────────────┐   │
│  │ "The AfDB has committed  │   │
│  │  to Phase I of the       │   │
│  │  Technical Secretariat..." │   │
│  │             ^^^^^^^^^^^^  │   │
│  └──────────────────────────┘   │
│                                  │
│  Suggested fix:                  │
│  Replace "committed to" with     │
│  "signalled strong interest in"  │
│                                  │
│  [Approve with fix] [Edit] [Reject]│
└─────────────────────────────────┘
```

---

## 9. Phase-by-Phase Execution Plan

### Phase 0 (COMPLETE)
FastAPI scaffold, Postgres + pgvector, gate Pass 1, ingest endpoint,
agent harness (echo_analyst), CI + Railway deploy. Baseline measured.

### Phase 1 (PARTIALLY COMPLETE — gap audit in TA.0)
Content pipeline live: deliberation, HERALD/JARVIS, gate Pass 2,
the AfCEN Platform fork (BrightBean) rebranded, delivery, social
posting, Nexus Brief, no-reply engine, notifications, Control Tower v0.

### Phase 2A — Content Complete
**Goal:** the content team uses Campaign OS as their primary interface.
Every content edge case (sensitivity, unblock conditions, partner
permissions, channels, track separation) enforced by architecture.

**TA.0 — Audit + rebrand + Celery+Redis + app map + RBAC.**
**TA.1 — Content intake: Google Sheets sync, normalization, model.**
**TA.2 — Sensitivity + verification enforcement in the gate.**
**TA.3 — Agentic content surfaces: curation, ideas rail, composer,
         calendar agent, inline gate pre-check.**
**TA.4 — Multi-channel edge cases: Nexus pairing, gated briefs,
         Joseph routing, articles, X derivation.**
**TA.5 — Eval system + reflection loop + voice profiles + heatmap.**
**TA.6 — Content module views, approvals, agents fleet view.**

**Exit gate (signed by Lazarus + Nduta):**
- Real intake sheet syncing 2+ weeks without issues.
- 4 consecutive content cycles without manual rescue.
- Every sensitivity/condition edge case enforced in prod.
- Gate first-pass ≥85% rising, zero incidents.
- ≥1 reflection diff applied with measured improvement.
- Platform in daily use by Nduta + ≥2 leads.

### Phase 2B — Joseph's Platform
**Goal:** Joseph uses Campaign OS before every meeting and after every
conversation. The agents brief him, draft for him, and queue follow-
through automatically.

**TB.0 — Remove n8n; wire all integrations in-process.**
**TB.1 — Joseph's voice profile v1.**
**TB.2 — Dossier engine (L0/L1/L2, orchestrator-worker).**
**TB.3 — Pre-meeting flow (T-5/T-2/T-1/T-0 cascade).**
**TB.4 — Post-meeting capture (voice + structured form + extraction).**
**TB.5 — Deck module (blocks, skeletons, assembly, continuity, edits).**
**TB.6 — Joseph's personal content (his voice, Nexus desk section).**
**TB.7 — Joseph's principal dashboard (mobile + desktop full spec).**
**TB.8 — Data rooms + deal signals.**
**TB.9 — Eval suite + reflection for Joseph-layer agents.**

**Exit gate:**
- Pre-meeting flow firing for ≥3 real meetings.
- Post-meeting capture used for ≥5 real meetings; wiki revisions live.
- Voice profile v1 seeded and rubric-passing.
- Deck assembled for ≥3 live threads ≤20 min each.
- Joseph using the mobile brief daily.
- n8n fully removed (grep clean).

### Phase 2C — Nduta's Operational Layer
**Goal:** the team operates outreach from Campaign OS, not a
spreadsheet. CRM, sequences, import wizard, connected mailboxes,
grant triage — all Nduta's operational tools.

**TC.0 — CRM full build (orgs, contacts, threads, activities, tasks).**
**TC.1 — Excel import wizard (generic: mapping, dedup, error report).**
**TC.2 — Connected mailboxes (Gmail OAuth; deliverability guardrails).**
**TC.3 — Sequences + no-reply engine + reply triage.**
**TC.4 — Grant scanning UX + triage + deadline alerts.**
**TC.5 — Deliberation gains CRM context (threads to warm).**
**TC.6 — Self-healing v1 (trace-cited diagnosis + PRs).**
**TC.7 — Source ledger auto-update + Roundtable pack + UNGA surge +
         load test + handover runbooks.**

**FastAPI fully decommissioned before Phase 3.**

### Phase 3 — WAIIS Surge
Freetown, 16–19 November 2026. All ten tasks per the Phase 3 doc.
Key additions to Campaign OS: `waiis/` app with summit data models,
political gate extensions (HoS dual approval, deal confidentiality,
countdown milestone rule), the on-site offline logger, the WhatsApp-
deliverable magic-link approval page, the 48-hour commitment sweep,
and the post-Summit follow-through sequences.

### Phase 4 — Hardening (December 2026 – December 2027)
Runbooks, quarterly Deal Room automation, Phase-II fundraising
automation, T3 autonomy promotions, diff-category auto-apply flips,
cost optimisation, 2027 tentpole calendar.

---

## 10. CLAUDE.md (Updated, Definitive)

```markdown
# CLAUDE.md — Campaign OS

## What this project is
Campaign OS is AfCEN's internal resource-mobilisation operating system.
A single Django 5 project (rebranded fork of BrightBean Studio, AGPL-3.0)
containing the UI, agents, compliance gate, integrations, and all
background jobs. Master plan: docs/CAMPAIGN_OS_FULL_BUILD.md.
Current phase: docs/CURRENT_PHASE.md (update this file when a phase
is complete).

## Hard rules (never violate)
1. Only this project touches the operational Postgres. No external
   service gets DB credentials.
2. All schema changes via Django migrations. Never mutate schema ad hoc.
   Migrations must be reversible.
3. Every external action (post, email, deck send, brief delivery) calls
   the gate and writes to audit_log. No bypass routes. Including content
   typed directly into the platform's own editor.
4. Tier checks are code (apps/core/tiers.py), not prompts. Before any
   agent action executes, check autonomy_tiers. Protected classes
   (money/commitment claims, named partners, political, Tier-1 donors)
   are permanently T2-capped.
5. Agent constitutions are frozen files in apps/agents/constitutions/.
   Nothing in this codebase may write them. Changes require a PR with
   Joseph's sign-off.
6. No trace, no fix. Self-healing logic must cite trace IDs. No trace
   evidence = stop and report insufficient_evidence.
7. No secrets in code or commits. Env vars + vault only. .env gitignored.
   Add every new var to .env.example and docs/ENV.md.
8. Tests required. Every view, task, and agent action ships with
   pytest coverage. Gate rules ship with fixture-based rule tests.
   CI must be green before a task is "done".
9. No dependencies without a one-line justification in the PR.
10. AGPL compliance. Keep LICENSE, NOTICE ("modified by AfCEN, <date>"),
    and an About/License menu item with a Source link to the internal
    repo. No business logic or operational DB credentials in any AGPL-
    licensed code path that could be argued to be a separate work.
11. Strangler rule. Every table is owned by exactly one migration system
    at any time. Record ownership in docs/TABLE_OWNERSHIP.md.
12. n8n is fully removed. All integrations are Celery tasks or Django
    webhook views. grep -r "n8n" . must return zero results outside
    of docs/ADRs/.

## Stack (pinned — ADR required to change)
- Python 3.12 · Django 5 · Django REST Framework · Channels (WebSocket)
- Celery + Redis (broker, results, cache, Channels layer, locks)
- PostgreSQL + pgvector (Railway)
- Microsoft Agent Framework 1.0 (Python) on deepseek api
- Firecrawl v2 self-hosted on Azure Container Apps (FIRECRAWL_BASE_URL
  + FIRECRAWL_API_KEY — rotate the default token; probe on boot)
- Cloudflare R2 (media, voice notes, deck assets)- use railway instead bucket

- Google APIs: Calendar, Gmail, Sheets, Slides (service account + OAuth2)
- Ghost (Nexus Brief, direct API)
- DocSend + Google Drive (data rooms, webhook inbound)
- Monocle/OTel → traces in Postgres
- pytest + pytest-django · ruff · uv

## App map
apps/core/ · apps/gate/ · apps/agents/ · apps/ingestion/
apps/knowledge/ · apps/content/ · apps/crm/ · apps/decks/
apps/grants/ · apps/learning/ · apps/notifications/
apps/integrations/ · apps/webhooks/ · apps/publishing/
apps/waiis/ (Phase 3)
modules/ (HTMX view apps: home, pipeline, content_board, ideas,
          composer, agents_view, learning_log, knowledge_browser,
          admin_panel, waiis_ops, joseph/)

## Definition of done (every task)
Code + tests green locally and in CI + migration if schema changed +
docs/ updated if contracts or ENV changed + acceptance check from the
phase doc passes + Lazarus review.

## Commands
make dev      # Django runserver (local)
make worker   # Celery worker
make beat     # Celery beat
make migrate  # django migrate
make mm m=""  # makemigrations
make test     # pytest
make lint     # ruff check + format --check
make seed     # seed agents, tiers, gate rules, sources
```

---

## 11. Expected Outcomes for Claude Code

When executing this specification, Claude Code should:

1. **Never proceed past an acceptance check without it passing.** If
   a check fails, diagnose, fix, and re-run the check. Do not move to
   the next task with a known failing acceptance check.

2. **Never add a shortcut that bypasses the gate.** If a code path
   needs to publish or send something and the gate feels cumbersome,
   the answer is to improve the gate integration, not to route around
   it. There are no legitimate bypass paths.

3. **Always write the test before considering a task done.** Especially
   for gate rules — every rule must have a fixture that makes it fire
   and a fixture that makes it pass.

4. **Consult the wiki before the web.** When implementing agent logic,
   the first tool call should be reading the relevant knowledge page.
   Only if the wiki is empty or stale should external calls be made.
   This is a code-level rule (the effort scaling function), not a
   prompt-level suggestion.

5. **The learning loops run before the platform is considered
   production-ready.** The eval system must be live, the reflection
   loop must have run at least once, and at least one playbook diff
   must have been applied and measured before Phase 2A's exit gate
   can be signed.

6. **Read PHASE1_GAP.md before any Phase 2A task.** The first
   deliverable of Phase 2A is the gap audit. Do not assume Phase 1
   is complete — verify it.

7. **The mobile experience is not an afterthought.** Every Joseph-
   facing view must be tested at 375px before the task is marked done.
   Offline behaviour must be tested with simulated network throttling.

8. **The Friday digest must be real.** It must contain actual numbers
   from the actual database. It must be drafted by HERALD using
   its voice rules. It must pass the gate. It is not a template
   with hardcoded text.

9. **When in doubt about whether something is a gate violation,
   it is.** The cost of a false positive is one human approval tap.
   The cost of a false negative is a compliance incident that could
   terminate a partnership.

10. **Phase 3 does not start until FastAPI is decommissioned.** This
    is a hard prerequisite. Verify with a grep and a Railway service
    check before executing T3.0.
```