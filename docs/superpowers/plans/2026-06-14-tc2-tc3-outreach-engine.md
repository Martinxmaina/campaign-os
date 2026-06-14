# Phase 2C — Outreach email engine (TC.2 + TC.3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. TDD, one commit per
> task. Tests: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <paths> -q -p no:warnings`.
> Do NOT run the whole suite per task. CSP-safe templates (no inline handlers; Alpine @click + hx-*; nonce on
> <script>); desktop templates `{% extends "base.html" %}`. requirements.txt is the prod install source —
> add any new runtime dep there + lazy-import heavy libs. Mock ALL network (gmail, gate) in tests.

**Goal:** A Django outreach engine — per-owner Gmail send, deliverability guardrails, gate-on-every-email,
multi-step sequences, no-reply follow-ups, and reply-triage — built on `apps/crm`.

**Architecture:** New `apps/outreach/` (engine) over `apps/crm` (threads/contacts) + `integrations/gmail`
(transport) + the gate client. Per-owner Gmail is the live sender; Instantly is a stub seam. The
agent-service sequences engine is retired. Design captured in this session's brainstorm (2026-06-14).

**Tech Stack:** Django 5.1, Celery beat, google-api-python-client (already in requirements), httpx (gate
client), HTMX/Alpine/Tailwind, pytest-django.

---

### Task 1: `apps/outreach` scaffold + Mailbox / MailboxSend / SuppressionEntry models
**Files:** Create `apps/outreach/{__init__,apps,models,admin}.py`, `apps/outreach/migrations/__init__.py`,
`apps/outreach/tests/__init__.py`, `apps/outreach/tests/test_models.py`; Modify `config/settings/base.py`
(add `"apps.outreach"` to LOCAL_APPS).
- [ ] **Step 1: Failing tests.** Create a `Mailbox(user, email, daily_cap=50)`; `MailboxSend(mailbox, date,
  count)` unique on (mailbox, date); `SuppressionEntry(email="x@y.org", reason="unsubscribe")` unique on email.
  Assert round-trip + `Mailbox.effective_cap_for(week_index)` returns 20 (wk0), 35 (wk1), 50 (wk2+).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** the three models (reuse `apps/crm.TimestampedUUID` base or a local one), `Mailbox`
  with `google_integration FK→apps.joseph.GoogleIntegration` (null ok), `status`, `ramp_started_at`, and an
  `effective_cap_for(week_index)` helper (`[20,35][week] if week<2 else daily_cap`). Register in admin. Add to
  LOCAL_APPS. `makemigrations outreach`.
- [ ] **Step 4: Run, expect pass** + migrate clean.
- [ ] **Step 5: Commit** `feat(outreach): apps/outreach scaffold + Mailbox/MailboxSend/SuppressionEntry`.

### Task 2: Gmail send transport
**Files:** Modify `integrations/gmail.py`; Test `apps/outreach/tests/test_gmail_send.py`
- [ ] **Step 1: Failing test.** `send_message(service, to="a@b.org", subject="s", body_html="<p>h</p>",
  headers={"In-Reply-To":"<m1>"})` builds a MIME message, base64url-encodes it, and calls
  `service.users().messages().send(userId="me", body={"raw":...})`; returns the sent id (mock the service).
  Assert `In-Reply-To`/`References` headers are set when provided.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** `send_message(...)` using stdlib `email.mime` + base64url; **lazy-import google**
  inside `build_gmail_service` already; `send_message` only needs stdlib + the passed service.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(gmail): outbound send_message (messages.send + In-Reply-To)`.

### Task 3: EmailSender + guarded_send (deliverability)
**Files:** Create `apps/outreach/senders.py`, `apps/outreach/exceptions.py`; Test
`apps/outreach/tests/test_senders.py`
- [ ] **Step 1: Failing tests.** `guarded_send(mailbox, to, subject, body, thread, gate_id)`:
  (a) suppressed `to` → raises `AddressSuppressed`, transport NOT called; (b) at cap → `CapExceeded`,
  transport NOT called; (c) success → appends unsubscribe footer + List-Unsubscribe header, calls the
  Gmail sender, increments `MailboxSend`, writes a `crm.Activity(activity_type="email_sent")` on the thread,
  returns the message id. `GmailEmailSender.send` delegates to `integrations.gmail.send_message`;
  `InstantlyEmailSender.send` raises `NotImplementedError`.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** `exceptions.py` (`AddressSuppressed`, `CapExceeded`, `GateBlocked`); `senders.py`
  with the protocol, `GmailEmailSender`, `InstantlyEmailSender` (stub), and `guarded_send` doing
  suppression→cap/ramp→unsubscribe-injection→send→count→Activity (all in the adapter). Ramp week from
  `(today - mailbox.ramp_started_at).days // 7`.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(outreach): EmailSender + guarded_send (cap/ramp/suppression/unsubscribe + Activity)`.

### Task 4: Gate-on-send
**Files:** Create `apps/outreach/gating.py`; Test `apps/outreach/tests/test_gating.py`
- [ ] **Step 1: Failing test.** `gate_or_block(body, track, author)` calls the existing gate client (mock);
  verdict `pass` → returns gate_id; `flag`/`block` → raises `GateBlocked` (carrying the findings). A
  `send_email(thread, subject, body)` high-level fn runs `gate_or_block` then `guarded_send`; a blocked body
  never reaches the sender (assert the sender mock not called) and queues an approval (crm.Activity or a
  pending record).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** `gate_or_block` (reuse the gate client used by `apps/publisher`); `send_email`
  orchestrator. On block, record an approval-needed Activity/notification.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(outreach): gate-on-send (every outbound email gated, no bypass)`.

### Task 5: Sequences — models + enroll + advance
**Files:** Modify `apps/outreach/models.py` (SequenceTemplate, Sequence, SequenceStep); Create
`apps/outreach/sequences.py`, `apps/outreach/tasks.py`; Modify `jobs/schedules.py`; Test
`apps/outreach/tests/test_sequences.py`
- [ ] **Step 1: Failing tests.** `enroll(thread, template)` creates a Sequence + SequenceStep rows with
  `scheduled_for` = now + cumulative delay_days; `advance()` sends a due **email** step via `send_email`
  (mock) and marks it sent, and creates a `crm.Task` for a due **human-channel** step (linkedin/whatsapp/call)
  marking it task_open; a future step is untouched; a completed sequence sets status=completed. Beat task
  `outreach-advance` registered.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** the three models, `enroll`/`advance` in `sequences.py`, `@shared_task advance_sequences`
  in `tasks.py`, register `"outreach-advance"` (daily) in `jobs/schedules.py`. `makemigrations outreach`.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(outreach): sequences (templates/steps + enroll + daily advance)`.

### Task 6: No-reply follow-ups + reply-triage
**Files:** Modify `apps/outreach/tasks.py` (no_reply), Create `apps/outreach/triage.py`; Modify
`apps/joseph/tasks.py` (`sync_google_gmail` calls triage); Modify `jobs/schedules.py`; Test
`apps/outreach/tests/test_triage.py`
- [ ] **Step 1: Failing tests.** `triage_inbound(messages)` matches a message to a thread by `Contact.email`
  (and `In-Reply-To` against a sent SequenceStep) → creates `crm.Activity(email_reply)` + **pauses** the active
  Sequence + emits a reply-triage notification; an unmatched message → general inbox review (no thread touch).
  `run_no_reply()` for a thread with a sent step + no reply after N days advances/drafts a follow-up + sets
  traffic_light amber/red.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** `triage.py::triage_inbound`; call it from `sync_google_gmail` after fetching;
  `run_no_reply` in tasks.py; register `"outreach-no-reply"` (daily) in schedules.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(outreach): no-reply follow-ups + inbound reply-triage`.

### Task 7: OAuth gmail.send scope + mailbox connect/status UI
**Files:** Modify `scripts/get_google_refresh_token.py` (+gmail.send), `apps/outreach/senders.py` (scope guard);
Create `apps/outreach/views.py`, `apps/outreach/urls.py`, `templates/outreach/mailbox.html`; Modify
`config/urls.py`; Test `apps/outreach/tests/test_mailbox_views.py`
- [ ] **Step 1: Failing tests.** `guarded_send` raises a clear error if the mailbox's GoogleIntegration scopes
  lack `gmail.send` (no crash). `/outreach/mailbox/` → 200 for owner/admin/campaign_owner (shows cap, ramp
  week, today's count, suppression count), 403 for viewer; pause/resume toggles `Mailbox.status`.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** the scope guard, the mailbox status view + template, `_can_manage_outreach` gate,
  pause/resume; add `gmail.send` to the OAuth script SCOPES; mount `apps/outreach/urls` at `/outreach/`.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(outreach): gmail.send scope + mailbox connect/status UI`.

### Task 8: Thread send + sequence enroll UI + reply-triage queue + suppression + unsubscribe
**Files:** Create `apps/outreach/views_thread.py`, `templates/outreach/{_send_form,_sequence_panel,triage_queue,
suppression_list,unsubscribe}.html`; Modify `apps/outreach/urls.py`, `apps/crm/thread_views.py` (or joseph
thread drawer) to mount the send + enroll actions; `templates/base.html` (Outreach nav, role-gated); Test
`apps/outreach/tests/test_thread_outreach.py`
- [ ] **Step 1: Failing tests.** POST `/outreach/threads/<id>/send/` (subject+body) → gate+guarded_send (mock)
  → Activity + 200; POST `/outreach/threads/<id>/enroll/` (template) → creates a Sequence; `/outreach/triage/`
  lists reply-triage items; `/outreach/suppression/` lists + add/remove; GET `/unsubscribe/<token>/` (public,
  no auth) adds a `SuppressionEntry`. CSP-safe.
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** the thread send form + enroll action + sequence panel (step timeline), the triage
  queue + suppression list views, the public unsubscribe view (signed token → SuppressionEntry). Add the
  Outreach sidebar section (role-gated). 
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** `feat(outreach): thread send + sequence enroll + triage queue + suppression + unsubscribe`.

### Task 9: Retire agent-service sequences + TABLE_OWNERSHIP
**Files:** Modify `docs/TABLE_OWNERSHIP.md`; (agent-service) deprecate `app/services/sequences.py` usage —
remove its beat registration so it stops running on orphaned threads; Test `apps/outreach/tests/test_ownership.py`
- [ ] **Step 1: Failing test.** `docs/TABLE_OWNERSHIP.md` lists outreach tables (mailbox, sequences, suppression)
  → Django; and an assertion that the agent-service daily_sequences beat is no longer registered (or a note doc).
- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement** the ownership doc update; in agent-service, comment out / remove the
  `daily_sequences_and_noreply` beat registration (it operated on agent-service threads that no longer exist).
- [ ] **Step 4: Run, expect pass** (+ agent-service tests still green for the unregister).
- [ ] **Step 5: Commit** (Django + agent-service) `chore(outreach): retire agent-service sequences; TABLE_OWNERSHIP`.

---

## Self-review
- Coverage: mailboxes (T1), send transport (T2), guarded sender (T3), gate-on-send (T4), sequences (T5),
  no-reply + triage (T6), scope+mailbox UI (T7), thread/sequence/triage/suppression/unsubscribe UI (T8),
  retire agent-service + ownership (T9). All design sections covered. Instantly = stub (T3). 
- Placeholders: none — real code/contracts per task.
- Type consistency: `guarded_send`/`AddressSuppressed`/`CapExceeded` (T3) used by T4/T5/T8; `gate_or_block`/
  `GateBlocked`/`send_email` (T4) used by T5/T8; `enroll`/`advance` (T5) used by T6/T8; `Mailbox.effective_cap_for`
  (T1) used by T3. Consistent.
- Build order 1→9 sequential (share models.py/urls.py/tasks.py/base.html/schedules.py). T2+T9 touch
  integrations/agent-service.
- After all tasks: full Django suite + agent-service suite (T9). Higher-risk (sends real email once consented)
  — do NOT auto-deploy; verify + the gmail.send re-consent is a user step before any live send.
