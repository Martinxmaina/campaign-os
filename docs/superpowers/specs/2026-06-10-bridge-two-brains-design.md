# Design: Bridge the Two Brains (Intake → HERALD → Publish)

**Date:** 2026-06-10
**Status:** Approved — ready for implementation plan
**Author:** Campaign OS team

## Problem

Campaign OS runs two disconnected systems:

- **agent-service** (FastAPI + DeepSeek, own Postgres): HERALD drafts from its own wiki/news signals; fires on a schedule; exposes `/ideas`, `/content/items`, `/threads`, `/agents/herald/draft`, `/approvals/{id}/decide`.
- **Campaign OS / Django** (the dispatch platform): the Phase 2 work — Google Sheets sync → `ContentIntake`, intake board, settings, gate. Console pages are read-only mirrors of agent-service.

The Phase 2 pipeline (sheet → `ContentIntake` → `build_intake_context()` → gate) dead-ends. `build_intake_context()` is wired to nothing. HERALD never sees the synced sheet. There is no trigger from the platform, the new pages are unlinked in the sidebar, and approved drafts never become publishable Posts.

## Goal

Wire the two systems so the full loop flows end to end:

```
Google Sheet → ContentIntake → push as brief → HERALD draft → review
   → approve in console → auto-create Django Post → gate → publish to social
```

## Decisions (locked)

1. **Integration model:** Django pushes intake → agent-service (via the existing `POST /agents/herald/draft` `brief` parameter; no new storage on agent-service).
2. **Draft trigger:** auto on sync (new accepted items) + manual "Draft now" button on the intake board.
3. **Draft → publish:** approve in console → Django auto-creates a `Post` + `PlatformPost`, runs the gate, queues it.
4. **Publish testing:** wire all 5 channel adapters now; real posting lights up per channel as each platform's OAuth app credentials arrive.

## Architecture

### Component 1 — Intake → HERALD bridge

**Sector mapping** (`apps/content_intake/sector_map.py`):
```
"energy" / "Energy" / "Power"            → energy
"agribusiness" / "Agriculture" / "Food"  → agribusiness
"ai" / "AI" / "AI 10Bn" / "Artificial"   → ai
(anything else)                          → general
```

**Brief assembly** (`apps/content_intake/herald_bridge.py`):
```python
def build_brief(intake) -> str:
    parts = [intake.angle]
    if intake.proof_point:
        parts.append(f"Proof: {intake.proof_point}")
    if intake.target_audience:
        parts.append(f"Audience: {intake.target_audience}")
    if intake.channel_targets:
        chans = ", ".join(t.get("platform", "") for t in intake.channel_targets)
        parts.append(f"Channels: {chans}")
    return ". ".join(p for p in parts if p)
```

**Push call** (`request_herald_draft(intake)`):
- Eligibility: `status == "accepted"`, `sensitivity in (public_safe, partner_only)`, `is_schedulable`, not already drafted (`herald_drafted_at is None`).
- Calls `agent_post("/agents/herald/draft", {sector, brief, count: 1})`.
- On success: store the returned `variant_group` / first content_item id on the `ContentIntake` row (new fields: `herald_content_id`, `herald_drafted_at`), set `status = "drafting"`.
- On failure: log, leave status unchanged for retry on next sync.

**New `ContentIntake` fields** (migration):
- `herald_content_id = CharField(blank, default="")` — links to agent-service content_item
- `herald_drafted_at = DateTimeField(null=True)` — idempotency guard

### Component 2 — Auto-trigger + manual button

- **Auto:** in `sync_intake_sheet` task, after upserts, enqueue `request_herald_drafts_for_workspace.delay(workspace_id)` which iterates eligible items and calls `request_herald_draft`.
- **Manual:** intake board card gets a "Draft now" button → `POST /console/intake/<id>/draft/` → `request_herald_draft(intake)` → HTMX swap showing "Drafting…" then a link to the console draft.

### Component 3 — Sidebar UI

In `templates/base.html` Intelligence section, add after "Brain":
- **Intake** → `/console/intake/` (icon: clipboard)
- **News** → `/console/news` (icon: newspaper)

Add an activity indicator partial (`templates/console/_activity_badge.html`) showing `last_sync_at` and `last_draft_at` (from cache keys set by the sync + draft tasks), rendered in the Intelligence section header.

### Component 4 — Approve → auto-create Post

Extend `apps/approvals/console_views.py::approval_decide`. On `decision == "approve"`:
1. `agent_post("/approvals/{id}/decide", {"decision": "approve"})` (existing).
2. Fetch the content item: `safe_get("/content/items/{content_id}")`.
3. Resolve the originating `ContentIntake` (by `herald_content_id`) for channel targets + workspace.
4. Create `Post` (caption = body, workspace, title from intake angle) + one `PlatformPost` per resolved `SocialAccount` matching the channel targets.
5. Run the existing gate via the publisher engine path (sensitivity + conditions + agent-service gate); if it passes, transition to `scheduled`/queued; if blocked, leave as `draft` with the gate reason.
6. Link back: `Post.intake_source` set to the `ContentIntake`.

If no matching `SocialAccount` exists yet (no OAuth creds), create the `Post` in `draft` state with the channel intent recorded, so it's ready when the channel is connected.

### Component 5 — Wire all 5 providers

- Add the missing X/Twitter credential env slot to `config/settings/base.py` `PLATFORM_CREDENTIALS_FROM_ENV` (`twitter`) + `.env.example`.
- Verify connect-account OAuth flow renders for all visible platforms.
- No publishing code change — adapters already exist; real publishing activates per channel when its OAuth app credentials are set in Railway.

### Component 6 — Deploy verification

- Force a clean redeploy of web + worker from the latest commit.
- Verify: `/console/intake/` 200 (logged in), `/console/pipeline` shows agent-service threads, a live `POST /agents/herald/draft` round-trip from the platform produces a content_item, sidebar shows Intake + News.

## Data Flow

```
[Google Sheet]
   │  15-min beat: sync_intake_sheet
   ▼
[ContentIntake rows]  ──auto──►  request_herald_drafts_for_workspace
   │  manual: "Draft now" button         │
   │                                      ▼
   │                          agent_post /agents/herald/draft {sector, brief}
   │                                      │
   │                                      ▼
   │                          [agent-service content_item + gate verdict]
   │                                      │  appears in /console/drafts, /console/approvals
   ▼                                      ▼
[intake board]                    approve in console
                                          │
                                          ▼
                          Django creates Post + PlatformPost
                                          │  existing gate (sensitivity + conditions + agent-service)
                                          ▼
                          [publisher engine → provider adapters → LinkedIn/X/Meta/...]
```

## Testing

- `sector_map`: unit tests for each pillar string → sector.
- `build_brief`: assembles angle/proof/audience/channels; handles empty fields.
- `request_herald_draft`: eligibility gating (skips private_hold, non-accepted, already-drafted); mocks `agent_post`; asserts fields set on success, unchanged on failure.
- Auto-trigger: sync creates accepted item → draft task enqueued (mock `.delay`).
- Manual button view: POST drafts, returns HTMX partial, requires login + workspace.
- Approve flow: mock content item fetch → asserts `Post` + `PlatformPost` created with caption + channel targets, gate run, `intake_source` linked; no-SocialAccount path leaves Post in draft.
- Sidebar: Intake + News links present and resolve.

## Out of Scope

- Deliberation (`/ideas`) producing ranked queues — separate agent-service concern.
- Voice profiles, smart scheduling (TA.5 learning).
- New social provider adapters — only wiring existing ones.
- Auto-publish without human approval (explicitly rejected — comms safety).

## Files

**New (Django):**
- `apps/content_intake/sector_map.py` + test
- `apps/content_intake/herald_bridge.py` + test
- `apps/content_intake/migrations/000X_herald_link_fields.py`
- `templates/console/_activity_badge.html`

**Modified (Django):**
- `apps/content_intake/models.py` — add `herald_content_id`, `herald_drafted_at`
- `apps/content_intake/tasks.py` — `request_herald_drafts_for_workspace` task; call from sync
- `apps/content_intake/views.py` + `config/console_urls.py` — "Draft now" view + route
- `templates/content_intake/_card.html` — Draft now button
- `apps/approvals/console_views.py` — approve → create Post
- `templates/base.html` — sidebar Intake + News links + activity badge
- `config/settings/base.py` + `.env.example` — twitter credential slot

**Verification only:** provider adapters, deploy.
