# Joseph's meeting loop — TB.3 pre-meeting cascade + TB.4 post-meeting capture & extraction

> Subagent-driven, TDD, one commit per task. Tests per task only:
> `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <p> -q -p no:warnings`.
> CSP-safe (Alpine @click / hx-*, nonce on every <script>); desktop templates {% extends "base.html" %};
> reuse BrightBean tokens (.card, .btn-brand, font-display Georgia, orange --primary, warm stone). Gate every
> task behind `_can_access_joseph`. Do NOT run the whole suite per task — orchestrator runs it once at the end.

**Goal:** Close the loop around a meeting. Before: a linked calendar event triggers a pre-meeting cascade
(dossier refresh → gate-checked talking points → "I'm going in"). After: a one-tap capture (voice note OR
quick form) → async transcription+extraction → an `ExtractedMeeting` of accept/edit/dismiss items that route
into Activities, Tasks, intake ideas, a wiki-revision queue, and a warmth rescore.

**Build philosophy (decided):** the whole loop lives in **Django now**, with **transcription and AI extraction
as deterministic seams** — `transcription.transcribe(audio_file) -> str` and
`extraction.extract(transcript, thread) -> dict` are pure functions returning a stable shape, marked
`# SEAM: real Whisper / agent-service ATLAS wiring lands later`. This makes the entire loop testable and
shippable today; swapping in the real model is a one-function change with the tests already written.

**Grounding (verified):**
- Calendar: `apps/joseph/models.py::CalendarEvent` (google_event_id unique, attendees JSON, linked_thread_id str,
  briefing_status str, raw JSON). Sync seam `integrations/google_calendar.py`; Today strip `views._today_events`;
  unlinked-suggestion seam `intelligence.JosephIntelligence._unlinked_calendar_events`.
- CRM canonical in Django: `apps/crm/models.py` Organization / Contact / OutreachThread / Activity
  (activity_type incl. `meeting`, `commitment_recorded`, `note`, `stage_advanced`) / Task (type incl.
  `capture_meeting`, `confirm_commitment`; status open/completed/dismissed; owner FK; due date; drafted_content).
- Dossier reader seam: `apps/joseph/readers.py` (compile_dossier / get_dossier / get_thread) +
  `apps/joseph/intelligence.py::JosephIntelligence._l0` (WHO/WHY NOW/HOOK/RED FLAGS/WARM PATH from a dossier) —
  reuse for talking points.
- Notifications: single entry point `apps/notifications/engine.py::notify(user, event_type, title, body, data)`;
  `event_type` is validated against `notifications.models.EventType` — **new meeting event types must be added there**.
- Scoring/rescore: `apps/crm/scoring.py::score_thread_features` + `apps/crm/tasks.py::score_all_threads` /
  `_features_for` (warmth is an input) — warmth-delta route updates `thread.warmth` then rescore.
- Content intake: `apps/content_intake/models.py::ContentIntake` (status IDEA, submitted_by FK, pillar_theme,
  sensitivity PUBLIC_SAFE/PARTNER_ONLY/PRIVATE_HOLD/CONFIDENTIAL, workspace FK).
- Storage: `config/settings/base.py` — S3Boto3Storage when `S3_*` env present (Railway R2), else FileSystemStorage
  (dev/test). A plain `FileField` is R2-backed in prod automatically; no bespoke upload code needed.
- Gate: status-language Pass-1 is the publish gate; for talking points reuse the same status-language check the
  composer/publisher path uses (no "commitment confirmed" before it is). `_can_access_joseph` at views.py:23.
- Test fixture: `joseph` (owner WorkspaceMembership + force_login) in apps/joseph/tests; settings `config.settings.test`.

---

### Task 1: Calendar ↔ thread auto-linking + confirm-linkage
**Files:** `apps/joseph/models.py` (+migration), `apps/joseph/linkage.py` (new), `apps/joseph/views.py`,
`apps/joseph/urls.py`, `apps/joseph/intelligence.py`; Test `apps/joseph/tests/test_calendar_linkage.py`
- Failing tests: a CalendarEvent whose title/attendees match an Organization/Contact gets `linked_thread_id`
  set with a confidence ≥0.9 auto-link; a 0.5–0.9 match is returned as a *suggestion* (not auto-linked) and
  appears via the unlinked/suggestion seam; `POST /joseph/calendar/<google_event_id>/link/` with a thread id
  links it (role-gated, CSRF, 200/redirect); a non-match links nothing.
- Implement: add `CalendarEvent.briefing_status` choices (`none|linked|briefed|captured`), `talking_points`
  (JSONField default list), `prep_stages` (JSONField default list — fired cascade stages, idempotency),
  `capture_status` (`none|prompted|captured|deferred`), `defer_until` (nullable dt). New `linkage.py`:
  `match_event_to_thread(event, *, threshold=0.9) -> (thread|None, confidence)` (token-set ratio on org name +
  attendee email/name vs Contact email/name; reuse rapidfuzz if present else a stdlib SequenceMatcher). A
  `link_event(event, thread)` setter. Wire confirm route + reflect suggestions in `_unlinked_calendar_events`.
- Commit `feat(joseph): calendar event ↔ thread auto-linking + confirm-linkage (TB.3)`.

### Task 2: Pre-meeting cascade (T-5 / T-2 / T-0) — Celery + gate-checked talking points
**Files:** `apps/joseph/meeting_prep.py` (new), `apps/joseph/tasks.py` (new or extend), `jobs/schedules.py`,
`apps/notifications/models.py` (EventType), `apps/joseph/talking_points.py` (new);
Test `apps/joseph/tests/test_meeting_prep.py`
- Failing tests: `check_meeting_prep()` on a linked event 5 days out fires the **T-5** stage (requests a dossier
  refresh via `readers.compile_dossier` + a `notify(... MEETING_PREP ...)`) and records it in `prep_stages` so a
  second run does NOT re-fire (idempotent); an event 2 days out fires **T-2** (drafts talking points — 3 bullets
  per track from the L0/dossier — runs them through the status-language gate, stores on
  `event.talking_points`, notifies with the L0 summary); an event today fires **T-0** (sets briefing_status
  `briefed`, marks brief ready for the "I'm going in" capture). Talking points that contain a banned
  status-language phrase are rewritten/flagged by the gate (assert the gate ran).
- Implement: add `EventType.MEETING_PREP`. `talking_points.draft(thread) -> list[str]` builds from
  `JosephIntelligence().brief(thread)` hooks/why-now; `gate_talking_points(points) -> list[str]` runs the same
  status-language Pass-1 used on publish. `check_meeting_prep()` iterates linked future events, computes
  days-to-start, fires the right stage idempotently. Beat entry `joseph-meeting-prep` (every 30 min).
- Commit `feat(joseph): pre-meeting cascade T-5/T-2/T-0 with gate-checked talking points (TB.3)`.

### Task 3: Meeting-capture data model (VoiceNote / ExtractedMeeting / ExtractedItem / WikiRevisionCandidate)
**Files:** `apps/joseph/models.py` (+migration); Test `apps/joseph/tests/test_meeting_models.py`
- Failing tests: a `VoiceNote` (FileField, thread FK, optional calendar_event FK, status
  `uploaded|transcribing|transcribed|extracted|failed`, transcript text, created_by) persists and its file uses
  the configured storage; an `ExtractedMeeting` (thread FK, optional voice_note FK, source `voice|form`,
  transcript, warmth_delta `warmer|same|cooler|null`, relationship_notes, status `pending|confirmed`) with
  `ExtractedItem` children (kind in the routing set below, description, confidence float, verbatim_quote,
  proposed_due, proposed_owner FK, wiki_update_candidate bool, payload JSON, state
  `pending|accepted|edited|dismissed`); a `WikiRevisionCandidate` (org/thread FK, signal text, proposed_change,
  source meeting FK, status `proposed|applied|dismissed`) — `proposed` by default, never auto-applied.
- Kind set: `commitment_financial`, `commitment_intro`, `commitment_follow_up`, `interest_expressed`,
  `objection_raised`, `strategy_signal`, `intelligence_signal`, `next_step`, `content_idea`.
- Commit `feat(joseph): meeting-capture models (voice note, extracted meeting/items, wiki revision queue) (TB.4)`.

### Task 4: Post-meeting capture surface (voice / quick-form / defer) + prompt
**Files:** `apps/joseph/views.py`, `apps/joseph/urls.py`, `templates/joseph/capture.html` (new),
`apps/joseph/tasks.py` (capture-prompt task), `apps/notifications/models.py` (EventType);
Test `apps/joseph/tests/test_capture.py`
- Failing tests: `GET /joseph/capture/<thread_id>/` renders three paths (voice record, quick form 5 fields:
  commitments / next step / due date / warmth delta / share-toggle, defer) — role-gated, CSP-safe;
  `POST .../voice/` (multipart) creates a VoiceNote (status uploaded) and enqueues extraction (assert task
  enqueued, eager in test); `POST .../form/` creates an ExtractedMeeting(source=form, status=pending) + items
  from the 5 fields directly (no transcription); `POST .../defer/` sets capture_status=deferred + defer_until
  (+2h) and schedules an escalation. `send_capture_prompts()` notifies the owner for an event that ended ≤N min
  ago with no capture (MEETING_CAPTURE), idempotent via capture_status.
- Implement: add `EventType.MEETING_CAPTURE`. Voice upload writes the FileField (R2 in prod, FS in test). Defer
  escalation: a follow-up notify to the backstop/Nduta after 24h if still uncaptured. Beat entry
  `joseph-capture-prompts` (every 15 min).
- Commit `feat(joseph): post-meeting capture surface — voice/quick-form/defer + prompt (TB.4)`.

### Task 5: Async extraction pipeline (transcription seam → extraction seam → ExtractedMeeting)
**Files:** `apps/joseph/transcription.py` (new, SEAM), `apps/joseph/extraction.py` (new, SEAM),
`apps/joseph/tasks.py` (extract task); Test `apps/joseph/tests/test_extraction.py`
- Failing tests: `extract_meeting(voice_note_id)` transitions the VoiceNote uploaded→transcribed→extracted,
  writes a transcript, and produces an ExtractedMeeting with items whose kinds are drawn from the routing set;
  idempotent (re-run does not duplicate); a failure path sets status=failed without raising. The transcription
  seam returns a deterministic transcript for a fixture audio; the extraction seam returns a stable structured
  dict (commitments / next_steps / intelligence_signals / content_ideas / warmth_delta / relationship_notes).
- Implement: `transcription.transcribe(voice_note) -> str` marked `# SEAM: real Whisper/Google STT later`
  (returns any stored transcript override for tests, else a placeholder). `extraction.extract(transcript,
  thread) -> dict` marked `# SEAM: real agent-service ATLAS pass later` (deterministic heuristic mapping so the
  shape + routing are exercised). `extract_meeting()` Celery task chains them and persists items (state=pending).
- Commit `feat(joseph): async meeting extraction pipeline with transcription/ATLAS seams (TB.4)`.

### Task 6: One-tap confirm + routing into Activities/Tasks/intake/wiki/warmth
**Files:** `apps/joseph/views.py`, `apps/joseph/urls.py`, `apps/joseph/routing.py` (new),
`templates/joseph/meeting_confirm.html` (new); Test `apps/joseph/tests/test_meeting_confirm.py`
- Failing tests: `GET /joseph/meeting/<extracted_meeting_id>/` lists items with accept/edit/dismiss + a
  bulk-accept; accepting routes each kind correctly —
  `commitment_*` → Activity(`commitment_recorded`) **+** a stage-proposal surfaced to Joseph's queue
  (Task `confirm_commitment` owner=Joseph); `interest_expressed|objection_raised|strategy_signal` →
  Activity(`note`) only (no stage change); `next_step` → Task (owner defaults to Joseph, due=proposed_due);
  `intelligence_signal` with wiki_update_candidate → a WikiRevisionCandidate(status=proposed, **not applied**);
  `content_idea` → ContentIntake(status=IDEA, submitted_by=Joseph, pillar pre-filled, sensitivity inferred from
  track); confirming with a warmth_delta updates `thread.warmth` and triggers a rescore; a dismissed item logs
  an Activity(`note`, "outcome logged") and creates none of the above. Confirm marks the meeting `confirmed`.
- Implement: `routing.apply_item(item, *, by_user)` switch; `routing.apply_warmth(meeting)`; the confirm view
  iterates accepted items. CSP-safe POST forms.
- Commit `feat(joseph): one-tap meeting confirm + routing to activities/tasks/intake/wiki/warmth (TB.4)`.

### Task 7: Joseph surface wiring (Today prep + capture entry + drawer extracted-meetings)
**Files:** `templates/joseph/home_desktop.html`, `templates/joseph/home_mobile.html`,
`templates/joseph/thread_drawer.html`, `apps/joseph/views.py` (home + drawer context),
`apps/joseph/intelligence.py` (proposals: pending-confirm meetings + linkage suggestions);
Test `apps/joseph/tests/test_meeting_surface.py`
- Failing tests: the Today strip shows a linked meeting's prep status + an "I'm going in" link to
  `/joseph/capture/<thread_id>/`; an event that ended with no capture shows a "Capture now" entry; the thread
  drawer lists that thread's ExtractedMeetings with a link to the confirm screen; a pending-confirm meeting and
  a linkage suggestion appear in Joseph's action queue (proposals). Pages stay 200 + role-gated + CSP-safe.
- Implement: thread cards/Today gain the capture CTA; drawer gets an "Meetings" section; proposals() merges
  pending-confirm meetings + linkage suggestions as ActionCards. Styling only beyond that — reuse tokens.
- Commit `feat(joseph): wire meeting loop into Today, capture entry, and thread drawer (TB.4)`.

---
## Self-review
Coverage: linkage (T1) → cascade+talking points (T2) → models (T3) → capture (T4) → extraction (T5) →
confirm+routing (T6) → surface (T7). Sequential & dependent (shared models/views/urls + migrations) → build
one task at a time in the main tree, each build→review→fix. Seams (transcription, ATLAS extraction) are
deterministic and clearly marked so the loop is fully testable now and the real model is a one-function swap.
After all 7: full Django suite, deploy dispatch web, smoke. Then resume TB.5 (decks) / TB.8 / TB.9.
