# PHASE 2B BUILD — Joseph's Principal Intelligence Platform
**Version 2.0 · Campaign OS · Single Django project**
**Executor:** Claude Code · **Prereq:** Phase 2A exit gate signed
**n8n:** fully removed from this phase and from CLAUDE.md. All integrations
are in-process: Celery tasks, Django webhook views, and direct API calls.
No workflow orchestrator sits outside the codebase.

**Scope:** what Joseph personally interacts with — intelligence briefings,
his personal voice on all channels, deal-flow oversight, pitch deck
generation, and the meeting cycle (prep → capture → follow-through).
Nduta and the team own the CRM, sequences, and outreach operations; that
is a separate Phase 2C document. This document is about Joseph as a
principal actor, not an administrator.

**Joseph's three jobs in the platform:**
1. Consume intelligence (read what the agents know, be briefed before
   every conversation, know where every deal stands).
2. Speak as himself (his personal LinkedIn, personal emails, voice,
   the Nexus Brief's principal perspective — drafted by agents, in his
   voice, approved by him).
3. Make judgment calls (advance a deal, request a deck, confirm a
   commitment, escalate a thread, override a recommendation).

**Joseph does NOT do in Campaign OS:** sequence management, contact
enrichment, CRM data entry, grant scanning, calendar management,
follow-up scheduling. Those are team operations.

**UX contract (governs every decision in this phase):**
- **Mobile (375px, offline-capable, 3-second load):** editorial surface.
  One screen of signal. One-tap actions. Works on any connection.
  Pre-loaded in service-worker cache before meetings.
- **Desktop (full browser):** operational surface. Full intelligence,
  full deck preview and edit, full deal-flow view, wiki browser.
  Content-differentiated from mobile, not just resized.

Standing rules: ordered tasks, acceptance gates, agents via the harness,
nothing external without the gate, constitutions frozen, no trace no fix,
tests + CI per task.

---

## TB.0 — Remove n8n, wire all integrations in-process

Every integration that was routed through n8n becomes either a Celery
periodic task or a Django webhook view. Complete list:

**Calendar (Google Calendar API, direct):**
`integrations/google_calendar.py` — OAuth2 per user (Joseph's account
first; others in Phase 2C). Celery beat (every 5 min): fetch upcoming
events → match against `organizations`/`contacts` by name fuzzy-match
→ `calendar_events` table (event_id, title, start, attendees parsed,
linked_thread nullable, briefing_status). Django view `POST
/webhooks/google/calendar/` receives push notifications for changes
(faster than polling). Thread linkage: if a match is confident, auto-link
with a notification for confirmation; if ambiguous, surface in Joseph's
action queue as a linkage suggestion.

**Gmail (Google Gmail API, direct):**
`integrations/gmail.py` — OAuth2 per connected mailbox. Celery beat
(every 10 min): Gmail history sync via `users.history.list` → new
messages parsed → raw into `ingest_items` (source_type=email_inbound).
Django view `POST /webhooks/google/gmail/` for push notifications.
Inbound routing: matched to a thread → activity record + reply triage
queue; unmatched → general inbox review queue.

**Google Sheets (Google Sheets API, direct):**
`integrations/google_sheets.py` — service account (read+optional write).
Celery beat (every 15 min) syncs the content intake sheet (already
specified in Phase 2A TA.1). Used here also for the outreach tracker
until Phase 2C's CRM import wizard is live.

**Firecrawl (already in-process, verify):** confirm all Firecrawl jobs
are Celery tasks calling the self-hosted instance directly. No n8n
intermediary. Scrape callbacks are Django webhook views `POST
/webhooks/firecrawl/crawl/{job_id}/`.

**All other webhooks** (DocSend/Drive access events, social platform
events from the AfCEN Platform publishing layer) are Django views under
`/webhooks/` with HMAC verification middleware. Every inbound webhook
writes to `ingest_items` and returns 200 immediately; processing is
async via Celery.

**Remove:** every reference to n8n in CLAUDE.md, the implementation
plan, ENV.md, and any workflow YAML files. Remove `INGEST_API_KEYS`
(the n8n static key mechanism); replace with per-integration HMAC
secrets in the vault. Update ADR-004 to record the n8n removal.

**Accept:** `grep -r "n8n" .` returns zero results outside of docs/ADR;
calendar events for Joseph's account appear in `calendar_events` within
5 min of creation; a Gmail reply to a seeded thread lands as an activity
within 10 min; Firecrawl crawl completion arrives via webhook and queues
a wiki compile; all inbound webhooks reject bad HMAC signatures (test
each handler).

---

## TB.1 — Joseph's voice profile (the foundation of his personal brand)

Before any draft goes to Joseph, the system needs to know how he sounds.

**Voice profile structure** (stored in `playbook_versions`, scope=user,
user=joseph): written in the same versioned playbook format as the agent
playbooks, because it goes through the same reflection pipeline. Sections:
- `tone`: direct, data-led, authoritative but not academic, African
  perspective as a strength not a qualifier, no hedging language.
- `openers`: patterns he uses and avoids (never starts with "I", never
  opens with a question on LinkedIn, often opens with a bold assertion
  or a number).
- `hooks_by_audience`: how he frames things differently for DFIs vs
  philanthropies vs governments vs tech ecosystem.
- `banned_phrases`: corporate filler he never uses — "synergies",
  "ecosystem play", "leverage", "unlock" used as a verb loosely.
- `signature_moves`: the SE4ALL precedent argument, the "concept note
  vs. operational engine" framing, the catalytic capital logic.
- `length_by_channel`: LinkedIn (250–400 words tight), email (3 paragraphs
  max for cold, longer for warm follow-up), X (punchy, no threads unless
  it earns it), voice/audio (conversational, first person, stories).

**Seeding:** HERALD analyzes Joseph's existing approved posts and sent
emails (available after TB.0 Gmail sync + Phase 2A content history) to
draft v1 of each section. Joseph reviews on desktop (diff view, same UI
as agent playbook diffs). He edits directly. This becomes v1.

**Learning:** every time Joseph edits a HERALD draft of his content, the
delta is an outcome record. Weekly reflection proposes voice profile diffs
with those edits as evidence — Joseph approves his own voice changes.
Over time the profile converges on his actual voice rather than an
approximation.

**Validation test:** two fixture drafts in Joseph's voice — one
LinkedIn post on the AI 10Bn, one email to a Rockefeller VP. Both must
pass a voice-rubric eval (banned phrases absent, opener pattern correct,
length in range, signature moves present where context warrants). A
third fixture in a clearly non-Joseph voice must fail the same rubric.

**Accept:** v1 profile seeded from real content; diff review screen works
on desktop; voice rubric eval passes/fails the three fixtures correctly;
reflection cycle proposes a diff on Joseph's edit history.

---

## TB.2 — Intelligence layer: the dossier engine (ATLAS orchestrator-worker)

Joseph's single most important pre-meeting tool. Three tiers, each a
complete artifact:

**L0 — the mobile brief (≤300 words, one screen):**
```
WHO:       [Org name] · [Contact name, role]
WHY NOW:   [Single most relevant signal from the last 30 days]
HOOK:      [One sentence recommendation per track — max 2 tracks]
RED FLAGS: [Max 3 bullets, most important first]
WARM PATH: [Best intro route if one exists; else "cold approach"]
FRESHNESS: [Compiled X hours/days ago · Sources: N]
```
Designed to be read in 90 seconds. Loads from service-worker cache
if offline. Rendered as a card, not a document.

**L1 — the one-pager (5-min read, desktop):**
L0 + recent grants/investments (last 3 years with amounts where public),
stated public priorities vs. our tracks, key decision-makers and their
stated positions, AfCEN relationship history (activities log summary).

**L2 — deep intelligence (20-min thorough read, desktop):**
L1 + full strategy analysis, all known principals with bios and verbatim
recent statements, org network (board/advisors/co-investors/portfolio),
comparable deals they have done (structure/size/stage/outcome), full
regulatory and reputational considerations, complete source citations with
trust scores from the source ledger, wiki page cross-links.

**Orchestration (MAF, orchestrator-worker):**
Planner reads the wiki page first at the appropriate tier (L0 request
on a fresh wiki → return directly, zero web calls; L2 request or stale
wiki → spawn subagents). Parallel subagents, each with an explicit scope,
objective, output format, tool guidance, and effort bound:
- `[org_strategy]` — Firecrawl scrape of their website + annual reports;
  web search for recent statements; wiki page update.
- `[principals]` — LinkedIn profiles + recent posts (Firecrawl); named
  individuals in recent press; wiki update.
- `[recent_grants]` — search for their grants announced/awarded last
  36 months; cross-reference with our tracks.
- `[warm_paths]` — search shared connections, board overlaps with AfCEN
  advisors, alumni networks, prior interactions in activity log.
- `[comparable_deals]` — search for similar organizations they have funded
  in the African development/climate/AI space; structure/stage/size.

Each subagent writes to Postgres and returns a reference. Assembler
reads references, writes the three tiers, updates the wiki page abstract
if richer, logs the compile episode. Every web call goes through Firecrawl
(self-hosted); fallback to direct requests only for APIs (World Bank,
IMF, AfDB documents).

**Effort scaling rules (enforced in code, not prompt):**
- L0 + wiki fresh (<7 days) + no meeting scheduled → serve from wiki, no
  subagents, no Firecrawl calls.
- L0 + meeting in ≤5 days → refresh L0 subagents only (principals +
  org_strategy); skip comparable_deals.
- L2 → all subagents; full depth.
- Source budget per subagent: max 8 Firecrawl pages; excess → stop and
  note "further sources available on request".

**Proactive refresh (Celery beat, daily):**
- Meeting in ≤14 days + dossier >7 days old → auto-refresh L0+L1,
  notify Joseph.
- Active thread (stage ≥ proposal) + dossier >21 days old → flag for
  refresh on pipeline view.
- Breaking ingest item about this org (from the curation queue) →
  targeted refresh of the affected section only; notify if material.

**Accept:** Wave-1 dossier e2e ≤15 min; ≥5 trust-scored sources; parallel
subagents visible in one trace tree; L0 card ≤300 words, renders on 375px
and serves from cache offline; effort-scaling: fresh wiki + L0 → zero
Firecrawl calls (trace assertion); proactive refresh fires on the 14-day
fixture; breaking ingest triggers a targeted section refresh.

---

## TB.3 — Pre-meeting flow (the complete meeting preparation cycle)

**Calendar linkage:**
A new `calendar_events` entry matching a known org/contact →
Joseph's action queue: "Meeting with [name] detected — link to thread?
[Yes, link] [It's different] [Skip]". One tap. Auto-link if confidence
>90% (exact org name match + Joseph as attendee); otherwise surface for
confirmation.

**On confirmed link, the preparation cascade runs automatically:**

T-5 days:
- Dossier refresh (L0+L1, proactive; L2 if Joseph requests).
- Deck assembly triggered if no current deck or deck >30 days old
  for this thread (details in TB.5).
- Notification: "Rockefeller meeting in 5 days. Brief and deck draft
  ready." (mobile push + in-app).

T-2 days:
- L0 brief pushed to mobile notification (tappable to the brief card).
- Talking points drafted: 3 bullets per relevant track drawn from
  hook_by_track in the dossier + recent content performance on
  topics relevant to this funder (e.g. "your data-sovereignty post
  got 3.2× average engagement with DFI audiences this month — open
  with that framing"). Gate-checked (status language discipline
  applies even to internal briefing documents).
- Any open tasks on this thread surface with a "before you meet" label.

Morning of (T-0):
- L0 brief card cached to service worker (available offline all day).
- One-tap "I'm going into this meeting" button that timestamps the
  meeting start and pre-loads the capture interface.

**Post-meeting (TB.4 triggers immediately after).**

**Accept:** fixture meeting created in Google Calendar with Rockefeller
in the title → auto-linked to the correct thread (>90% confidence test);
T-5 notification fires; talking points cite dossier sources and a recent
content performance metric; brief card offline on airplane-mode test;
gate-check on talking points catches a "commitment confirmed" phrase
(trap fixture).

---

## TB.4 — Post-meeting capture and intelligence extraction

The moment a calendar event ends, Campaign OS acts.

**Immediate prompt (≤2 min after event end):**
Mobile notification: "Just finished with [name] — capture now."
Tap → one of three paths:
1. **Voice note:** press-and-hold to record (R2 upload, offline queue
   with retry, reconciles on reconnect).
2. **Quick form:** 5 fields — commitments made (free text), next step,
   follow-up due (date picker), changed warmth (warmer/same/cooler),
   share with team (toggle).
3. **Defer:** "Remind me in 2 hours" (Celery delay; if no capture
   within 24h, escalates to Nduta as a flagged thread).

**Async extraction (ATLAS, Celery task, within 10 min of upload):**
Voice note → Whisper transcription (or Google Speech-to-Text; pick
per cost/quality eval in ADR-006) → ATLAS extraction pass:

```python
ExtractedMeeting(
    commitments: list[Commitment(
        type: financial|intro_promised|follow_up_agreed|
              interest_expressed|objection_raised|strategy_signal,
        description: str,
        confidence: float,
        verbatim_quote: str | None,
        proposed_due: date | None,
        proposed_owner: str | None
    )],
    next_steps: list[NextStep(action, due, suggested_owner)],
    intelligence_signals: list[Signal(
        type: strategy_shift|personnel_change|portfolio_signal|
              competitive_intel|relationship_signal,
        description: str,
        wiki_update_candidate: bool
    )],
    content_ideas: list[Idea(angle, pillar, audience)],
    warmth_delta: warmer | same | cooler | None,
    relationship_notes: str | None
)
```

**One-tap confirm screen (mobile + desktop):**
Each extracted item shown as a card with accept/edit/dismiss. Accepted:
- `financial|follow_up_agreed|intro_promised` commitments → `activities`
  row + thread stage proposal to Joseph's queue.
- `interest_expressed|objection_raised|strategy_signal` → `activities`
  row (no stage change; informs next approach).
- Next steps → `tasks` with owner (Joseph assigns; defaults to himself).
- Intelligence signals with `wiki_update_candidate=true` → revision queue
  (not auto-applied; ATLAS proposes the diff, Joseph or Nduta confirms).
- Content ideas → intake items (pillar/owner pre-filled, status=idea,
  submitted_by=joseph, sensitivity inferred from the thread's track).
- Warmth delta → DEAL-ENGINE rescore trigger.
- Dismissed items logged as outcomes (trains extraction quality over time).

**Accept:** voice-note fixture (90-second recording about a Rockefeller
call with 3 commitments, 2 next steps, 1 strategy signal) →
ExtractedMeeting schema populated correctly; bulk-accept works in one tap;
content idea appears in the intake board with Joseph as submitter;
wiki revision candidate is in the queue, not auto-applied; defer path
escalates to Nduta after 24h (test with time mock); offline queue
reconciles on reconnect.

---

## TB.5 — Pitch deck generation (Joseph's request + proactive)

**Block library (in `decks/`):**
Import from the four collateral docs as the seed (one-pager, pitch deck,
module, WAIIS prospectus). Every claim/stat/bio/case-study is a block:
```python
Block(
    id: uuid,
    type: claim|stat|bio|case_study|precedent|governance|ask|
          pillar_description|team|closing,
    track: core|programs|waiis|ai10bn | list,  # cross-track walled
    audience_type: philanthropy_anchor|bilateral_ta|
                   corporate_sponsor|dfi|internal,
    sensitivity: public_safe|partner_only|confidential,
    confirmation_status: confirmed|unconfirmed|needs_review,
    content_md: str,
    source_ref: str | None,  # citation for claims/stats
    owner: user FK,
    version: int,
    superseded_by: uuid | None
)
```
The SE4ALL TA figure → `confirmation_status=unconfirmed`, assembly-
blocked until Will confirms (the block has a `confirm_action` that sets
this, logged to audit). Stale-figure report: `GET /admin/decks/stale`
lists sent decks containing superseded block versions.

**Skeletons (JSON, per audience × house × use_case):**
`philanthropy_anchor` · `bilateral_ta` · `corporate_sponsor` · `dfi`
· `principal_brief` (Joseph's internal pre-meeting briefing format,
not for sending; shorter, denser, no governance/branding slides).
Each defines: slide_order[], per-slot {accepted_block_types[], required:
bool, max_blocks: int}. Skeleton validator: every accepted block type
must have at least one confirmed block in the library.

**Assembly (Celery task, triggered by request or proactive):**

```
assemble_deck(thread_id, skeleton_id, ask_amount=None, presenter=joseph)
```

1. Load thread dossier (L2 preferred, L1 fallback; if neither, trigger
   dossier compile first and queue deck after).
2. Block selection: filter by track (cross-track = `DeckAssemblyError`,
   not a warning; log the offending block ID), audience_type, sensitivity
   ≤ thread sensitivity, confirmation_status=confirmed only.
3. Write the personalization layer (the one generated part):
   - Opening slide: framing language drawn from dossier `hook_by_track`
     for the target audience; mirrors the funder's stated vocabulary
     (e.g. "digital public infrastructure" for GIZ; "catalytic capital"
     for Rockefeller; "energy-compute nexus" for GEAPP; "blended finance
     architecture" for DFIs).
   - Ask slide: populated from the thread's track + ask_amount (if
     provided) or from the standard ask block.
   - Throughout: Joseph's voice profile applied to any generated text
     (not to block content, which is pre-approved).
4. Google Slides API: copy the house master for this track → `batchUpdate`
   replacing named text placeholders + image placeholder slots (images
   from R2 via `insertImage`). Charts pre-built in the master; only data
   values updated via `updateCells` on embedded Sheets. Never agent-drawn
   charts.
5. Gate verification: every slide's text content is checked against the
   gate (Pass 1 + Pass 2). Each claim in the generated personalization
   layer must cite a dossier source or a block ID (untraceable claims
   flag). Any finding blocks the deck from being sent (not from being
   reviewed — Joseph can still see a flagged draft).
6. Write `deck_registry`: thread, skeleton, block_versions jsonb,
   presenter, gate_id, slides_url, slides_id (for future edits), status:
   draft, flagged findings if any.
7. Notify Joseph: "Draft deck ready — [funder], [skeleton], [N] slides,
   [gate status]." With a direct link to the review screen.

**Continuity (deck #2+ for the same thread):**
Read `deck_registry` + activities since the last deck:
- Drop slides whose blocks were already in the previous deck (show a
  "what changed" panel listing dropped and new slides).
- Insert "Progress since [date]" slide: populated from `activities`
  (commitments made, meetings held, milestones hit) and `commitments`
  since last deck. This is a generated slide, Joseph reviews it first.
- Update the ask slide if thread stage has advanced.
- Note any funder intelligence updates since the last deck (from the
  dossier diff).

**Proactive trigger (from TB.3):**
Meeting detected T-5 days, no current deck or deck >30 days old →
auto-assemble using the default skeleton for the thread's audience_type
and track → notify Joseph.

**Joseph's customisation loop (desktop only):**
Deck review screen:
- Left: Slides embed (iframe, live from Google Slides) or PDF preview
  (fallback for offline / bandwidth-constrained).
- Right: edit panel with three modes:
  - **Section request** (natural language): "Make the ask slide more
    direct." "Add the Mission 300 precedent to the leverage section."
    "Swap the governance slide for the team slide." → deck agent
    makes targeted edits → re-gate-verifies changed slides only
    → updates the embed → logs the edit as an episode.
  - **Block swap**: browse the block library filtered to compatible
    blocks for a slot → swap in one tap → re-gate-verify.
  - **Direct edit**: open the slide in Google Slides directly for
    fine-grained control (the system can't track these edits; a
    "sync from Slides" button pulls the current state back in for
    gate re-verification).
- Version history: every assembly + edit cycle as a version; Joseph
  can revert to any prior version.

**Learning:**
`deck_registry` rows joined to `activities` outcomes weekly. The
reflection loop tunes: block selection heuristics (which blocks in which
positions correlate with meeting outcomes); personalization vocabulary
(which funder-language mappings produce dossier-cited openers that
Joseph doesn't edit); skeleton ordering (which slide sequences Joseph
consistently reorders). Diffs proposed with evidence, approved by Nduta,
applied as playbook vN+1.

**Accept:**
- New-funder deck assembled, gate-verified, Slides link ≤20 min.
- Unconfirmed block (SE4ALL) → assembly fails listing the exact slide +
  field.
- Cross-track block → `DeckAssemblyError` with block ID.
- Deck #2 fixture: progress-since slide present, repeated slides dropped,
  funder intelligence delta noted.
- Proactive trigger fires on 5-day meeting fixture.
- Section request ("make the ask more direct") → only that slide re-gate-
  verified; episode logged with the request as input and changed slide
  refs as output.
- Stale-figure report correctly lists the sent deck after the SE4ALL block
  is confirmed then superseded.
- Offline PDF fallback renders the last-fetched deck with a "last synced"
  timestamp.

---

## TB.6 — Joseph's personal content (his voice on all channels)

Joseph's personal brand covers: his LinkedIn personal page, his
personal email, and the "principal perspective" section of the Nexus
Brief. These are distinct from the org channels (AfCEN, WAIIS, AI 10Bn)
that the content team manages.

**The personal content workflow:**
Joseph's content can originate four ways:
1. **From the ideas rail**: a deliberation or curation idea flagged
   "Joseph amplification recommended" or channeled to "Joseph personal"
   → his personal queue; he picks, HERALD drafts in his voice profile.
2. **From a meeting capture**: a content idea extracted from a voice note
   → intake item with Joseph as submitter; appears in his queue.
3. **From Joseph directly**: he opens the composer, types a rough angle
   or records a voice note → HERALD drafts in his voice.
4. **Proactive proposals**: HERALD + ATLAS identify moments where Joseph's
   personal voice would land better than an org channel (e.g. a breaking
   development in a funder's focus area, a personal story that matches
   a current campaign moment) → surfaced as a proposal in his queue with
   the reasoning attached.

**The Nexus Brief principal perspective:**
The Wednesday assembly (JARVIS) pre-drafts a "From Joseph's desk" section
as part of the Brief. Joseph reviews it Thursday morning (mobile-first);
inline edit or approve. His edits are the voice profile training signal.
If he doesn't act by Thursday noon, Nduta gets a nudge (not Joseph
again — he is not pinged twice).

**Gate on personal content:**
Joseph's personal posts still go through the gate. His relationship with
the gate is slightly different: he gets the findings with suggested fixes,
not a hard block on his own content (a human can override the gate on
their own posts with a reason, logged to audit). Findings on status
language, unconfirmed figures, or partner-separation breaches are still
surfaced; he decides. His account, his call — but the decision is audited.

**Accept:** four origination paths each produce a drafted post in Joseph's
voice (rubric-tested: banned phrases absent, opener pattern, length,
signature moves); Nexus Brief section drafted every Wednesday and in
his queue Thursday; gate findings surface on a personal post with the
override path available and audited; voice profile diff proposed after
3 edit sessions with evidence.

---

## TB.7 — Joseph's principal dashboard (the complete surface)

**Mobile (375px, offline-capable):**

`/joseph/` — requires Joseph's role; everything below loads from cache
if offline (service worker pre-caches on login and updates in background).

**Today strip (always top):**
- Meetings today with linked threads: [Org name] · [Time] · L0 brief
  card on tap · "I'm going in" button · "Capture after" button.
- Unlinked calendar events: "Possible: [event title] — link to a thread?"

**Action queue (sorted by urgency):**
- Gate escalations routed to Joseph (anything with a named partner,
  status language, or a number).
- Deck reviews ready for his sign-off.
- Stage-advance proposals from reply triage.
- Commitment confirmations from meeting capture.
- Calendar linkage suggestions.
- Nduta escalations (Red threads, SLA breaches).
Each card: one-tap approve/edit/reject/snooze. Magic-link capable —
a notification deep-link opens the card without a login screen if the
session is valid.

**Red threads (always visible, cannot be collapsed):**
Any thread where Joseph is owner or backstop and the traffic light is
Red, or a task is overdue. Tap → thread detail.

**Personal content queue:**
Drafted posts waiting for his approval, sorted by target publish date.
Tap → composer with the draft pre-loaded.

**Desktop (full browser):**

**Home:**
Capital funnel by track ($-weighted; click to thread list) · multiplier
line vs. baseline · escalations strip · today's action queue (same as
mobile but full context visible without tapping).

**Pipeline (the deal-flow view):**
Traffic-light kanban with columns per stage. Thread cards show:
- Org name + primary contact.
- Track badge + tier (Tier-1/Anchor/Wave-1/etc.).
- Days since last touch (color: green <7d, amber 7–14d, red >14d).
- Next action + due date.
- Dossier freshness (green <7d, amber 7–21d, red >21d with refresh button).
- Deck status (none / draft / sent / opened).
- Score + quintile badge.
Click → thread drawer.

**Thread drawer (the main workspace for any deal):**
Tabs:
- **Brief**: L0 always visible; toggle to L1; "Full intelligence →"
  opens the L2 dossier in a right panel.
- **Deck**: current deck embed (Slides or PDF); version picker; edit
  panel (TB.5's three modes: section request, block swap, direct edit).
- **Timeline**: all activities (append-only; agent actions and human
  actions distinguished by actor type); voice notes playable inline;
  meeting capture confirmations shown with the extraction confidence.
- **Intelligence**: the wiki page for this org, inline (L0/L1/L2
  toggle); recent ingest items from the curation queue about this org
  with ATLAS's relevance score; data room access events (who opened
  what, when, how long).
- **Tasks**: open tasks on this thread; Joseph can assign to himself
  or Nduta; drafted copy pre-loaded for human-channel tasks.
- **Sequence**: current sequence step, upcoming steps, sent history —
  read-only for Joseph (Nduta operates sequences; Joseph sees the state).
One-tap inline actions (always visible on the drawer header):
"Request deck" · "Log activity" · "Capture meeting" · "Advance stage"
· "Escalate to Nduta" · "Mark restricted".

**Calibration view:**
DEAL-ENGINE reply rate + meeting rate + stage-advance rate by score
quintile (bars). If the bars don't slope, scoring is decoration — Joseph
should know this and the system should say it plainly ("Calibration
indicates current scoring is not predictive — review recommended").
Historical calibration snapshots by month.

**Knowledge browser:**
Full wiki, filterable by entity_type (funder / org / person / initiative
/ topic). Joseph reads what the agents know before any conversation.
Search by keyword (pgvector semantic + text match). Each page: L0/L1/L2
toggle; revision history; source citations with trust scores; outgoing
wiki-links; linked threads.

**Personal content (desktop):**
His personal queue with full draft previews + gate findings. Composer
with the full voice-profile-aware HERALD. Voice note input (record in
browser → R2). Nexus Brief section in-context with the full Brief
preview.

**Accept:** scripted walkthrough covering: Joseph opens mobile before a
meeting → brief card loads from cache on airplane mode → taps "I'm going
in" → meeting ends → capture prompt fires → voice note recorded offline
→ reconnects → extraction in queue → bulk-confirms → content idea in
intake board → wiki revision in queue; then desktop: thread drawer covers
all tabs on a Wave-1 fixture thread; deck edit request changes only the
target slide; calibration chart slopes (or shows the warning); knowledge
browser returns the correct funder page with source citations. All without
developer assistance.

---

## TB.8 — Data rooms + deal signals

DocSend/Drive access events → `/webhooks/docsend/` or `/webhooks/drive/`
(HMAC verified) → `ingest_items` → `data_room_events` (append-only:
thread, document_name, document_url, opened_at, duration_s,
pages_viewed[], raw_payload).

**Thread drawer Intelligence tab:** access events rendered as a timeline
entry ("Rockefeller opened the deck 4 times in the last 48 hours,
spending 3 min on the ask slide").

**Deal signal engine (Celery task, on each new event):**
- 3+ document opens in 48h → opportunity notification to Joseph:
  "High engagement signal on [funder] — recommend a follow-up call
  within 48h." With a proposed task pre-drafted.
- Time-on-page >2× average on a specific slide → note in the thread
  Intelligence tab ("Extended time on the ask slide — this is what
  they're evaluating").
- First open of a deck that was sent >7 days ago → "Finally opened —
  the moment is fresh" notification with proposed next touch.

**Learning:** signal→outcome joins in the weekly reflection (did the
signal precede an advance within 14 days?). Thresholds tuned by the
DEAL-ENGINE reflection cycle.

**Accept:** access event → `data_room_events` <1 min; 3-open fixture →
notification with proposed task; time-on-ask-slide fixture → intelligence
note; first-open-after-7-days fixture → notification; signal→outcome
query returns data for the reflection loop.

---

## TB.9 — Outreach eval suite + Joseph-layer reflection

**Eval cases specific to this phase:**
- Dossier quality: L0 ≤300 words (hard assertion); L0 cites ≥3 sources
  (hard assertion); L0 correctly identifies red flags from the fixture
  funder profile (judge rubric); L2 contains verbatim principal
  statements from public sources (trace assertion: web call happened).
- Deck assembly: cross-track block always raises DeckAssemblyError
  (hard assertion); unconfirmed block always fails with correct message
  (hard assertion); personalization layer cites dossier vocabulary
  (judge rubric: funder's terminology present in generated text).
- Voice profile: banned phrases absent (hard assertion); opener pattern
  matches the profile (judge rubric); length in range by channel
  (hard assertion).
- Meeting capture: financial commitment extracted with >0.8 confidence
  on the fixture recording (judge rubric); wiki_update_candidate=true
  for strategy signals (hard assertion).
- Deal signal: 3-open fixture produces notification within 5 min
  (integration assertion).

**Reflection extended to Joseph-layer agents (ATLAS dossier, deck
assembly, DEAL-ENGINE scoring):**
Friday cycle now includes these agents. ATLAS diffs tune: search
strategies (wiki-first discipline — trace assertions verify this),
subagent scope definitions, source-budget rules. Deck agent diffs tune:
block selection heuristics, personalization vocabulary mappings,
skeleton ordering rules. All diffs through the standard evidence →
eval → approval → rollback-watch pipeline.

**Accept:** eval suite ≥20 cases covering each category above; one full
reflection cycle on real dossier + deck data produces at least one
evidenced diff per Joseph-layer agent; rollback drill repeated for
the deck agent specifically (the highest-stakes agent in this phase).

---

## Phase 2B exit checklist
- [ ] n8n fully removed; all integrations in-process (grep clean)
- [ ] Calendar linkage working for Joseph's account; pre-meeting flow
      firing for ≥3 real meetings (T-5/T-2/T-0 all verified in production)
- [ ] Post-meeting capture used for ≥5 real meetings; wiki revisions
      confirmed; content ideas appearing in the intake board
- [ ] Joseph's voice profile v1 seeded and reviewed; voice rubric eval
      passing; reflection proposed ≥1 diff on his edit history
- [ ] Wave-1 dossiers all at L2; L0 mobile brief ≤300 words, offline-
      capable, loads in <3s on throttled connection
- [ ] Proactive deck proposals firing on 5-day meeting fixtures in prod
- [ ] Deck assembled for ≥3 live threads ≤20 min each, gate-verified;
      Joseph's customisation loop exercised on ≥1 real deck
- [ ] Deck continuity (deck #2 with progress-since slide) tested on a
      real thread
- [ ] Deal signals firing; calibration chart showing real quintile data
      (or the "not predictive" warning if data insufficient)
- [ ] Joseph using the mobile brief daily before meetings (usage logged)
- [ ] Joseph's personal content queue in weekly use; Nexus Brief section
      in his queue every Thursday
- [ ] Eval suite ≥20 cases; ≥1 diff per Joseph-layer agent with evidence;
      deck-agent rollback drill passed
- [ ] Desktop thread drawer covering all tabs unaided by a developer

## Out of scope (Phase 2C, Nduta's operational layer)
CRM full build · sequences + no-reply engine · reply triage at scale ·
Excel import wizard · connected mailboxes · grant scanning UX ·
outreach team RBAC · WAIIS registration (Phase 3).