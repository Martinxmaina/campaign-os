# Design: Content Workflow Backbone

**Date:** 2026-06-11
**Status:** Approved — ready for implementation plan

## Problem

Intake items arrive as `idea` and get stuck — there is no way to accept them, move
them through stages, draft them, edit them, or get a scheduled item onto the calendar.
Three triaged symptoms share this one root cause:

- **#1 "Draft with HERALD" does nothing** — the Draft button only renders for
  `status=accepted`; 32/34 prod items are `idea` and there is no idea→accepted action.
- **#2 "Add to calendar" item doesn't appear** — the calendar grid is built only from
  `PlatformPost.effective_at`; the intake-created Post is channel-less (0 PlatformPosts)
  so it is invisible.
- **#5 No CRUD/Kanban/integration** — the `Idea` Kanban exists but is separate from
  `ContentIntake`; no "edit opens the existing item"; intake/composer/calendar aren't wired.

## Decisions (locked)

1. **Kanban view toggle** — keep the table; add a `[ Table | Board ]` toggle. Board view
   shows 3 drag-between columns: To Do / In Progress / Done.
2. **Auto-draft on move to In Progress** — dragging a card to In Progress accepts the item
   AND triggers HERALD (DeepSeek). A manual "Draft with HERALD" button stays on cards.
3. **Edit opens the composer; editable Post created at draft-time** — when HERALD drafts,
   create an editable Django `Post` (draft) pre-loaded with the AI copy; "Edit" opens it in
   the full composer. Approval gates publishing only.
4. **Calendar fix** — scheduling creates `PlatformPost`s from `channel_targets` for connected
   accounts AND the calendar also renders channel-less scheduled Posts.

## Architecture

### Component 1 — `board_stage` (derived, no new field)

Add a property on `ContentIntake`:

```python
_TODO = {"idea", "accepted", "held", "blocked"}
_IN_PROGRESS = {"drafting", "in_review", "approved"}
_DONE = {"scheduled", "published", "archived"}

@property
def board_stage(self) -> str:
    if self.status in self._DONE: return "done"
    if self.status in self._IN_PROGRESS: return "in_progress"
    return "todo"  # idea/accepted/held/blocked, and any unmapped
```

(`skipped`/`review_queue` are already excluded from the board query.)

### Component 2 — Kanban board view

`board(request)` gains `?view=board`. When set, render `board_kanban.html`: three columns,
each listing cards for items whose `board_stage` matches, workspace-scoped. Each card is
`_kanban_card.html` (pillar, angle, sensitivity badge, owner, 📎). Cards are draggable
(Alpine + native HTML5 drag, CSP-safe `@dragstart`/`@drop`); dropping in a column POSTs to
the stage endpoint. The existing table view is unchanged; a toggle link switches `?view=`.

### Component 3 — Stage transition (`POST .../intake/<pk>/stage/`)

`move_stage(request, intake_pk)` reads `to_stage` (todo|in_progress|done):

- **→ in_progress:** set `status=drafting`; call `request_herald_draft(intake)` (existing
  bridge — drafts via agent-service, sets `herald_content_id`); then ensure an editable
  Post exists via `ensure_draft_post(intake)` (Component 4). Returns the refreshed board.
- **→ done:** if the item has no scheduled Post yet, return a small schedule-picker partial
  (reuse the add-to-calendar dialog) targeting `add_to_calendar`; once scheduled,
  `schedule_intake_item` sets `status=scheduled`. If already scheduled, no-op.
- **→ todo:** set `status=accepted` (or `idea` if never drafted).

Blocked/sensitive items (`not is_schedulable`) cannot move to done — return a message.

### Component 4 — Draft-time editable Post (`ensure_draft_post`)

New `apps/content_intake/draft_post.py::ensure_draft_post(intake) -> Post`:
- If `intake.post` exists, return it.
- Else fetch the HERALD content item (`safe_get("/content/items/{intake.herald_content_id}")`)
  and build a draft Post from it, reusing the existing
  `apps.approvals.intake_publish.create_post_from_content(content, intake)` helper.
- If the content isn't ready yet (draft still running), create a minimal Post from the
  intake's angle/proof so the composer has something to open; the caption is refreshed on
  next view if the content item arrives later.

"Edit" links point to `composer:compose_edit` with `intake.post_id`.

### Component 5 — Calendar visibility fix (#2)

Two changes in `apps/calendar/views.py::calendar_view` month grid:
1. After the `platform_posts` loop that builds `posts_by_date`, add a second loop over
   `_get_filtered_posts(workspace, request)` filtered to `scheduled_at__date` in range and
   `platform_posts__isnull=True` (channel-less), appending a lightweight render object to
   `posts_by_date` so planning items show.
2. In `schedule_intake_item`, after setting `scheduled_at`, create a `PlatformPost` (status
   `draft`) for each connected `SocialAccount` whose platform matches the intake's
   `channel_targets` (so connected channels render natively and are publish-ready). Uses the
   `gate_bypassed=True` flag (human/AI-authored composer path) consistent with existing posts.

### Component 6 — Edit links + cross-references

- Intake `_panel.html` and `_kanban_card.html`: "✎ Edit in composer" → `compose_edit` for
  `intake.post` (shown once a Post exists).
- The composer/calendar already key off `Post`; the `intake.post` FK is the back-reference.

## Data model

- No migration: `board_stage` is a derived property; `intake.post` FK already exists;
  `Post`/`PlatformPost`/`gate_bypassed` already exist.

## Files

**New:**
- `apps/content_intake/draft_post.py` — `ensure_draft_post`
- `templates/content_intake/board_kanban.html`, `_kanban_card.html`
- tests: `test_board_stage.py`, `test_move_stage.py`, `test_draft_post.py`, `test_calendar_visibility.py`

**Modified:**
- `apps/content_intake/models.py` — `board_stage` property + lane constants
- `apps/content_intake/views.py` — `?view=board` branch, `move_stage` view
- `config/console_urls.py` — `intake-move-stage` route
- `apps/content_intake/intake_calendar.py` — create PlatformPosts for connected channels
- `apps/calendar/views.py` — render channel-less scheduled Posts in the month grid
- `templates/content_intake/board.html` — Table|Board toggle
- `templates/content_intake/_panel.html`, `_row.html` — Edit-in-composer link

## Testing

- `board_stage`: each status → correct lane.
- `move_stage` → in_progress: status=drafting, `request_herald_draft` called (mock),
  `ensure_draft_post` creates a Post linked to intake.
- `move_stage` → done without schedule: returns schedule picker; with schedule via
  `schedule_intake_item`: status=scheduled, Post.scheduled_at set.
- `move_stage` → todo: status reverts.
- `ensure_draft_post`: reuses existing Post; creates from content item (mock safe_get);
  minimal fallback when content not ready.
- `schedule_intake_item`: creates PlatformPost for a connected matching SocialAccount;
  none when no match (still schedulable as channel-less).
- calendar: a channel-less scheduled Post appears in the month grid `posts_by_date`.
- Edit link resolves to `composer:compose_edit` once `intake.post` exists.

## Out of scope (separate sub-projects)

Approval owner-routing (#4), Resend (#7), analytics (#6), pipeline (#9), date-picker
polish (#3), doc-links-on-calendar (#8). The Kanban drag uses native HTML5 DnD +
Alpine (CSP-safe); no drag library added.
