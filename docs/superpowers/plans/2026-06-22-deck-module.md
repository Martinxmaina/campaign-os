# Deck module — TB.5 pitch-deck generation (block library → assembly → review → continuity → customisation)

> Subagent-driven, TDD, one commit per task. Tests per task only:
> `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <p> -q -p no:warnings`.
> CSP-safe (Alpine @click / hx-*, nonce on every <script>); desktop templates {% extends "base.html" %};
> BrightBean tokens (.card, .btn-brand, font-display Georgia, orange --primary, warm stone). Gate Joseph-only
> views behind `_can_access_joseph`. Orchestrator runs the full suite once at the end — not per task.

**Goal:** Joseph can request (or proactively receive) a pitch deck for a thread that is *assembled from a
walled block library against an audience skeleton, gate-verified, source-cited, and reviewable/editable*, with
continuity across decks for the same thread. New Django app `apps/decks`.

**Build philosophy (decided, mirrors the meeting loop):** the deck **intelligence** is real — block library +
cross-track wall + skeletons + selection rules + gate-verification with citations + registry + continuity +
proactive trigger + review/version screens. The **render layer** (Google Slides `batchUpdate`/`insertImage`/
`updateCells`) and the **NL section-edit "deck agent"** are deterministic **SEAMS** (`# SEAM: real Google
Slides API / agent-service edit pass later`) — they need the still-pending Google creds and are pure render.
A deck assembles to a `DeckRegistry` row + a structured slide payload + a placeholder `slides_url`; swapping in
live Slides is a one-function change with tests already written.

**Grounding (verified):**
- Gate (authoritative, reuse — do NOT re-implement): `apps/publisher/gate_client.py` —
  `check_gate(content, content_type="email") -> {verdict, findings, gate_id, content_hash}` (POST /gate/check,
  raises `GateError`) and `verify_gate(gate_id)`. Pass-1+Pass-2 live in agent-service. Findings block *send*,
  not *review*.
- Dossier reader: `apps/joseph/readers.py` — `get_thread`, `get_dossier(dossier_id)`,
  `compile_dossier(thread_id)` (degrade to {} on AgentClientError). L0/L1/L2 + `hooks`/`hook_by_track` live in
  the dossier dict (see `JosephIntelligence._l0`).
- CRM canonical in Django: `apps/crm/models.py` OutreachThread (track core|programs|waiis|ai10bn; `restricted`
  bool, `sector`, `pillar`, `dossier_id`, `stage`, `owner`), Activity (`commitment_recorded`, `meeting`,
  `stage_advanced`), Organization. Threads + activities are the continuity source.
- Voice profile: applied to GENERATED text only via the agent-service `voice:joseph` seam (see
  [[project_tb1_voice_profile]]); block content is pre-approved and never voiced. Use a thin
  `apply_voice(text) -> text` seam that degrades to identity when the service is down.
- Storage: `config/settings/base.py` S3Boto3Storage when `S3_*` present (R2), else FS. Notifications:
  `apps/notifications/engine.notify(user, event_type, ...)` — add `EventType.DECK_READY`.
- Proactive hook point: `apps/joseph/meeting_prep.py::check_meeting_prep` T-5 stage (TB.3, just shipped) — add
  the "no current deck / deck >30d → assemble" trigger there.
- Add `"apps.decks"` to INSTALLED_APPS (config/settings/base.py near apps.joseph). New app, so low file contention.

---

### Task 1: Block library + skeletons + seed
**Files:** new `apps/decks/__init__.py`, `apps/decks/apps.py`, `apps/decks/models.py` (+migration),
`apps/decks/skeletons.py`, `apps/decks/management/commands/seed_blocks.py`; config/settings/base.py (INSTALLED_APPS);
Test `apps/decks/tests/test_blocks.py`, `apps/decks/tests/test_skeletons.py`
- Failing tests: a `Block` (id, type in {claim,stat,bio,case_study,precedent,governance,ask,pillar_description,
  team,closing}, track core|programs|waiis|ai10bn or list, audience_type philanthropy_anchor|bilateral_ta|
  corporate_sponsor|dfi|internal, sensitivity public_safe|partner_only|confidential, confirmation_status
  confirmed|unconfirmed|needs_review, content_md, source_ref nullable, owner FK, version int, superseded_by
  nullable self-FK) persists; `block.confirm(by_user)` flips confirmation_status→confirmed and writes an audit
  trail (assert logged); `skeletons.get(skeleton_id)` returns the 5 skeletons (philanthropy_anchor, bilateral_ta,
  corporate_sponsor, dfi, principal_brief), each with slide_order[] + per-slot {accepted_block_types[], required
  bool, max_blocks int}; `skeletons.validate(skeleton_id, blocks_qs)` fails when an accepted block type has zero
  confirmed blocks and passes when each has ≥1; `seed_blocks` creates a realistic AfCEN library (Mission 300,
  Rockefeller catalytic-capital, GEAPP energy-compute, GIZ DPI, plus a `stat` for the SE4ALL TA figure with
  `confirmation_status=unconfirmed`), idempotent.
- Commit `feat(decks): block library + audience skeletons + seed (TB.5)`.

### Task 2: Assembly engine (assemble_deck) — selection + personalization + gate-verify + registry
**Files:** `apps/decks/models.py` (DeckRegistry +migration), `apps/decks/assembly.py`, `apps/decks/slides.py`
(SEAM), `apps/decks/voice.py` (SEAM), `apps/decks/tasks.py`, `apps/notifications/models.py` (EventType);
Test `apps/decks/tests/test_assembly.py`
- Failing tests: `assemble_deck(thread_id, skeleton_id, ask_amount=None, presenter=joseph)` —
  (a) loads the dossier (L2 preferred, L1 fallback; if neither, calls compile_dossier then proceeds with what it
  has); (b) selects blocks filtered by track, audience_type, sensitivity ≤ thread sensitivity, and
  confirmation_status=confirmed ONLY; (c) a block whose track does not match the thread raises
  `DeckAssemblyError` naming the offending block id (cross-track wall, not a warning); (d) a *required* slot with
  no confirmed block (e.g. the unconfirmed SE4ALL stat) raises `DeckAssemblyError` listing the exact slide +
  field; (e) the generated personalization layer (opening framing from dossier `hook_by_track` + an
  audience→vocabulary map: Rockefeller "catalytic capital", GEAPP "energy-compute nexus", GIZ "digital public
  infrastructure", DFI "blended finance architecture"; ask slide from track + ask_amount) is run through
  `apply_voice()` then `check_gate()`; a gate finding lands on the registry and marks it un-sendable but still
  reviewable; every generated claim must cite a dossier source or a block id, else it is flagged "untraceable";
  (f) a `DeckRegistry` row is written (thread, skeleton, block_versions JSON, presenter, gate_id, slides_url
  [placeholder], slides_id, status=draft, findings) and `notify(...DECK_READY...)` fires.
- Implement: `slides.render(deck) -> {slides_url, slides_id}` SEAM (deterministic placeholder; marks where
  Google Slides batchUpdate/insertImage/updateCells lands). `voice.apply_voice(text)` SEAM (identity when
  agent-service down). Add `EventType.DECK_READY`.
- Commit `feat(decks): deck assembly engine — walled selection, cited personalization, gate-verify, registry (TB.5)`.

### Task 3: Deck review screen + version history + stale-figure report
**Files:** `apps/decks/models.py` (DeckVersion +migration), `apps/decks/views.py`, `apps/decks/urls.py`,
`config/console_urls.py` or joseph urls (mount), `templates/decks/review.html`, `templates/decks/_versions.html`;
Test `apps/decks/tests/test_review.py`
- Failing tests: `GET /joseph/decks/<deck_id>/` renders the review screen — a slide preview (rendered slide
  payload or a placeholder embed for the seam), the gate status + any flagged findings, the block list with
  citations, and a version-history rail; role-gated + CSP-safe. Each assembly/edit cycle is a `DeckVersion`
  (block_versions snapshot + slides payload); `POST /joseph/decks/<deck_id>/revert/<version_id>/` restores that
  version (new version row, not in-place). `GET /joseph/decks/stale/` lists *sent* decks whose registry holds a
  block version that has since been superseded (the offending block + deck). A draft deck appears in Joseph's
  action queue / a decks index.
- Commit `feat(decks): review screen + version history/revert + stale-figure report (TB.5)`.

### Task 4: Continuity (deck #2+) + proactive trigger from the pre-meeting cascade
**Files:** `apps/decks/continuity.py`, `apps/decks/assembly.py` (continuity branch), `apps/joseph/meeting_prep.py`
(T-5 proactive hook), `apps/decks/tasks.py`; Test `apps/decks/tests/test_continuity.py`,
`apps/joseph/tests/test_meeting_prep_deck.py`
- Failing tests: assembling a *second* deck for a thread that already has a sent deck — drops slides whose blocks
  were in the previous deck and returns a "what changed" summary (dropped + new slide lists); inserts a
  generated "Progress since <date>" slide populated from `Activity` rows (commitments/meetings/milestones) since
  the last deck (Joseph reviews it — status draft); updates the ask slide if the thread stage advanced since the
  last deck; notes dossier-diff funder updates. The proactive trigger: `check_meeting_prep` at T-5 for a linked
  thread with NO current deck (or newest deck >30 days old) enqueues `assemble_deck` with the default skeleton
  for the thread's audience_type+track and notifies Joseph — idempotent (records it in `prep_stages`, does not
  re-assemble on the next sweep).
- Commit `feat(decks): continuity (progress slide + diff) + proactive T-5 auto-assemble (TB.5)`.

### Task 5: Customisation loop — section request / block swap / direct-edit sync
**Files:** `apps/decks/views.py`, `apps/decks/urls.py`, `apps/decks/edits.py` (SEAM), `templates/decks/review.html`
(edit panel); Test `apps/decks/tests/test_edits.py`
- Failing tests: the review screen's right panel offers three modes —
  (1) **Section request** `POST /joseph/decks/<id>/edit/section/` with NL text → `edits.apply_section_request`
  (SEAM: deterministic targeted edit to the named slide) → re-runs `check_gate` on the CHANGED slide(s) only →
  writes a new DeckVersion → logs an episode/audit row;
  (2) **Block swap** `POST /joseph/decks/<id>/edit/swap/` browses blocks compatible with a slot (filtered by the
  slot's accepted_block_types + track + sensitivity + confirmed) and swaps one in → re-gate that slide → new
  version;
  (3) **Direct edit + sync**: `POST /joseph/decks/<id>/sync/` pulls the current Slides state back in (SEAM) and
  re-gate-verifies the whole deck.
  All role-gated + CSP-safe; each edit produces a version; revert (Task 3) still works across edits.
- Commit `feat(decks): customisation loop — section request / block swap / direct-edit sync, each re-gated (TB.5)`.

---
## Self-review
Coverage maps to the TB.5 spec: block library+skeletons (T1) → assembly with walled selection, cited
personalization, gate-verify, registry (T2) → review+versions+stale report (T3) → continuity+proactive (T4) →
customisation loop (T5). Sequential & dependent (T2–T5 build on T1 models + the registry) → build one task at a
time, each build→review→fix. Google Slides render, voice application, and the NL section-edit agent are
deterministic SEAMS so the whole module is testable now; live wiring is a per-seam swap once Google creds land.
After all 5: full Django suite, deploy dispatch web, smoke. Then TB.8 (data rooms + deal signals) / TB.9 (evals).
