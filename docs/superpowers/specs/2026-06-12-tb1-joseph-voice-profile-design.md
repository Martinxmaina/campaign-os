# Design: TB.1 — Joseph's Voice Profile

**Date:** 2026-06-12
**Status:** Approved — ready for implementation plan
**Phase:** 2B (Joseph's Principal Intelligence Platform), sub-project TB.1
**Repos:** agent-service (storage, application, reflection) + waiis-dispatch-platform (editor, eval, capture)

## Problem

Before HERALD drafts anything in Joseph's name, the system must know how he sounds. We need a
versioned voice profile that HERALD applies when drafting Joseph's content, seeded from
`docs/joseph.md`, editable by Joseph, validated by a rubric, and refined by a weekly loop on
his edits.

## Grounding (verified in code)

- agent-service `PlaybookVersion(agent_name, version, sector, body:JSONB)` — **no `scope`/`user`
  column**. We store the voice profile as `agent_name="voice:joseph"` (versioned), reusing the
  existing table + `load_latest_playbook`.
- HERALD `draft()` builds `system_extra` with `PLAYBOOK=json(...)` — the injection point for voice.
- **No reflection pipeline exists** in agent-service. The learning loop is built here as a
  concrete weekly voice-reflection task, not a generic framework.
- Django `apps/evals` (EvalCase/EvalRun + runner) hosts the voice rubric.

## Decisions (locked)

1. Storage in agent-service playbook (`agent_name="voice:joseph"`); HERALD applies it via a new
   `voice_user` param.
2. v1 seeded from `docs/joseph.md` content; Joseph edits in the UI.
3. Learning loop included now (concrete weekly task, not a generic reflection engine).

## Architecture

### Component 1 — Voice storage + endpoints (agent-service)

- Seed v1: a seed/migration inserts `PlaybookVersion(agent_name="voice:joseph", version=1, body=…)`
  with the 6 sections taken verbatim from `joseph.md` TB.1:
  `tone, openers, hooks_by_audience, banned_phrases, signature_moves, length_by_channel`.
- `load_voice(session, user) -> dict`: `load_latest_playbook(session, f"voice:{user}")`.
- New router `app/api/voice.py` (require_role "lead"):
  - `GET /voice/{user}` → latest body + version.
  - `PUT /voice/{user}` → body → insert a new `PlaybookVersion` (version = prev+1); returns new version.
  - `GET /voice/{user}/versions` → version list with created_at for the diff UI.

### Component 2 — HERALD applies the voice

- `HeraldDraftRequest.voice_user: str | None = None`; `draft(session, *, …, voice_user=None)`.
- When `voice_user` set, `voice = await load_voice(session, voice_user)` and append a VOICE block
  to `system_extra`:
  ```
  VOICE PROFILE (write in this person's voice; obey strictly):
  - Tone: {tone}
  - Openers: {openers}
  - NEVER use these phrases: {banned_phrases}
  - Length for this channel: {length_by_channel[channel]}
  - Use signature framings where they fit: {signature_moves}
  ```
- Empty/missing profile → no VOICE block (unchanged behavior).

### Component 3 — Django voice editor (`/joseph/voice/`)

- New `apps/joseph/` app (the Phase 2B home for Joseph surfaces) OR reuse `settings_manager`;
  use a new `apps/joseph/` app (`/joseph/voice/`), Joseph/owner-role gated.
- `voice_editor(request)`: `agent_get("/voice/joseph")` → render the 6 sections as editable fields
  + a version dropdown showing diffs vs the selected prior version.
- `voice_save(request)` (POST): assemble the body → `agent_post("/voice/joseph", body, method=PUT)`
  (extend the agent client to PUT) → redirect with the new version.
- Approve-diff action (Component 5): a proposed diff renders as a side-by-side; "Apply" saves it
  as a new version via the same PUT.

### Component 4 — Voice rubric eval (`apps/evals`)

- `apps/content_intake/voice_rubric.py::score_voice(text, channel, profile) -> dict`:
  `{passed: bool, failures: [str]}` checking:
  - no `banned_phrases` present (case-insensitive substring),
  - opener matches profile rules (not starting with "I"; LinkedIn not opening with a question),
  - word count within `length_by_channel[channel]` range,
  - at least one `signature_moves` cue present when the channel is LinkedIn/email (warn-only if absent).
- 3 fixtures wired as `apps/evals` EvalCases: LinkedIn-AI10Bn (pass), Rockefeller-email (pass),
  generic-corporate (fail — contains banned phrases / wrong opener).

### Component 5 — Learning loop

- **Capture (Django):** when Joseph edits a HERALD-drafted Post in the composer and saves, if the
  Post originated from HERALD (has `herald_content_id` via its intake link) and the author/owner is
  Joseph, record an edit-delta: POST to agent-service `POST /voice/joseph/edit-delta`
  `{original, edited, channel}`. Stored in a new `voice_edit_deltas` table (agent-service).
- **Weekly reflection (agent-service Celery/beat task `voice_reflect`):** aggregate unprocessed
  deltas for a user; run a HERALD/DeepSeek pass that, given the current profile + the edit deltas,
  proposes a minimal profile diff (which sections to change, with the deltas as evidence); store a
  `VoiceProposal(user, proposed_body, evidence, status=pending)`. Does NOT auto-apply.
- **Approve (Django editor):** pending `VoiceProposal` surfaces in `/joseph/voice/` as a diff;
  Joseph Apply → PUT new version (marks proposal applied) or Dismiss (logged).

## Data model

- agent-service: new tables `voice_edit_deltas`, `voice_proposals` (Alembic migration); voice profile
  reuses `playbook_versions` (no schema change). Django: no new model (reads via agent client); a
  small `apps/joseph` app with views only.

## Files

**agent-service:**
- `app/agents/voice.py` — `load_voice`, seed helper, proposal logic
- `app/api/voice.py` — GET/PUT/versions + edit-delta endpoints
- `app/services/herald.py` — `voice_user` param + VOICE injection
- `app/api/agents.py` — `voice_user` on `HeraldDraftRequest`
- `app/db/models/…` + Alembic migration — `voice_edit_deltas`, `voice_proposals`
- `app/jobs/voice.py` — weekly `voice_reflect` task; register in beat
- seed for `voice:joseph` v1
- tests

**waiis-dispatch-platform:**
- `apps/joseph/` (app, urls, `voice_editor` + `voice_save` + approve/dismiss views)
- `templates/joseph/voice_editor.html`
- `apps/content_intake/voice_rubric.py` + `apps/evals` fixtures
- composer save path: capture Joseph's HERALD-draft edits → agent-service edit-delta
- `apps/common/agent_client.py`: support PUT
- `config/urls.py`: mount `/joseph/`
- tests

## Testing

- agent-service: voice seed present; GET/PUT versions increment; HERALD draft with `voice_user`
  injects the VOICE block (assert system_extra contains banned-phrase rule); edit-delta stored;
  `voice_reflect` produces a pending VoiceProposal from seeded deltas.
- Django: voice editor renders 6 sections (Joseph-gated); save PUTs a new version; rubric eval
  passes the 2 Joseph fixtures + fails the non-Joseph one; edit-delta POSTed when Joseph edits a
  HERALD-origin post; pending proposal renders as a diff and Apply creates a new version.

## Out of scope

Gmail-sourced seeding (TB.0); auto-analysis seeding of real posts; other TB.* surfaces; a generic
reflection framework (this builds the voice loop concretely).
