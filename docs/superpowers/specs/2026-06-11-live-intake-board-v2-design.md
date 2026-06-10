# Design: Live Intake Board v2

**Date:** 2026-06-11
**Status:** Approved — ready for implementation plan

## Problem

The current intake board is a static, filterable card list. The team wants a real
working board: a selectable table with a detail panel, the sheet's document links
rendered and clickable, one-click "Draft with HERALD" and "Add to calendar" (single
and bulk), and a view that refreshes as the Google Sheet changes. Two concrete gaps
found in production:

1. **Doc links are never captured.** Every `ContentIntake.reference_links` is `[]`
   because Google Sheets `values().get()` returns only a cell's *visible text*, not
   embedded hyperlinks or Drive smart-chips. The sheet's docs are linked/chipped, so
   they are invisible to the sync.
2. **Duplicate rows.** The sheet syncs into two workspaces (`WAIIS`, `os`), so each
   idea appears twice. The board must scope to the current workspace.

## Decisions (locked)

1. **Layout:** hybrid — sortable table on the left, detail side-panel on the right.
2. **Selection:** row checkboxes → bulk action bar (Draft selected · Add selected to calendar).
3. **Doc links:** extract via grid API (hyperlink + chips); render as clickable chips
   in the side panel; pass doc titles/URLs to HERALD as source context. **Not** fetching
   full doc contents.
4. **Add to calendar:** date/time picker → create a draft `Post` from the item, link it
   back, place on the calendar, move status → `scheduled`.
5. **Live sync:** browser auto-refresh (~45s HTMX poll) + a "Sync now" button forcing an
   immediate pull. Background beat stays at 15 min.

## Architecture

### Component 1 — Doc-link extraction (`sheets_sync.py`)

Replace the values fetch with `spreadsheets().get(spreadsheetId, ranges=[range], includeGridData=True)`.
For each row, iterate `rowData.values[]` cells and extract links:

```python
def _extract_cell_links(cell: dict) -> list[dict]:
    """Return [{title, url, type}] from a cell's hyperlink + Drive chips."""
    links = []
    # 1. Whole-cell hyperlink (Insert > Link on the cell)
    uri = cell.get("hyperlink")
    if uri:
        links.append({"title": cell.get("formattedValue") or uri, "url": uri, "type": _link_type(uri)})
    # 2. Rich-text runs with per-run links (textFormatRuns + userEnteredFormat link)
    #    and Drive smart-chips (chipRuns[].chip.richLinkProperties.uri)
    for run in cell.get("chipRuns", []):
        chip = (run.get("chip") or {}).get("richLinkProperties") or {}
        u = chip.get("uri")
        if u:
            links.append({"title": chip.get("label") or u, "url": u, "type": _link_type(u)})
    return links


def _link_type(url: str) -> str:
    if "docs.google.com/document" in url: return "gdoc"
    if "docs.google.com/spreadsheets" in url: return "gsheet"
    if "drive.google.com" in url: return "gdrive"
    if url.lower().endswith(".pdf"): return "pdf"
    return "link"
```

Rows are still keyed by the existing column map. The "Doc links" column AND any
hyperlinked/chipped cell across the row contribute to `reference_links`. A new helper
`_get_sheet_grid(sheet_id, sheet_range)` returns the parsed grid; the existing
`_get_sheet_rows` is kept (re-derived from grid `formattedValue`) so current row
parsing is unchanged. Auto-detect of the tab name (already implemented) is preserved.

`reference_links` shape becomes a list of dicts `[{title, url, type}]` (was list of
bare strings). The sync writes the new shape; templates and agent context read it.

### Component 2 — Board table + side panel (`views.py`, templates)

- `board(request)` renders `board.html`: the table (workspace-scoped, excludes
  `skipped`), filters (status/pillar), and an empty side panel.
- `row_panel(request, intake_pk)` returns `_panel.html` for one item (HTMX target),
  with full fields, doc chips (`_doc_chips.html`), conditions, and action buttons.
- Table rows (`_row.html`) have a checkbox (`name="ids"`), are sortable by clicking
  headers (`?sort=pillar|status|priority|-created_at`), and `hx-get` the panel on click.
- A bulk action bar (in `board.html`) posts selected `ids` to the bulk endpoints.

### Component 3 — Actions

- **Draft (single):** existing `draft_now` view — extended so `herald_bridge.build_brief`
  appends `Sources: <doc title> (<url>); …` from `reference_links`.
- **Draft (bulk):** `draft_selected(request)` — POST `ids[]`; calls `request_herald_draft`
  for each eligible; returns updated rows.
- **Add to calendar (single+bulk):** `add_to_calendar(request)` — POST `ids[]` +
  `scheduled_at`; for each item calls a new `intake_calendar.schedule_intake_item(intake, when, user)`:
  - creates `Post(workspace, title=angle, caption=proof/angle)` if `intake.post` is None,
  - sets `post.scheduled_at = when`,
  - links `intake.post`, sets `intake.status = "scheduled"`,
  - creates a `CustomCalendarEvent` (or `QueueEntry`) marker so it shows on the calendar.
  Returns the updated row(s). Blocked items (`is_schedulable False`) are skipped with a message.

### Component 4 — Live sync (`views.py`, templates)

- `_table.html` partial wraps the table with `hx-get="{board table url}?partial=1"
  hx-trigger="every 45s"` so it self-refreshes.
- `sync_now(request)` — POST; runs `sync_sheet_to_intake(request.workspace)` synchronously,
  returns the refreshed table partial. Shows a "Synced just now" stamp.
- Background beat unchanged (15 min).

### Component 5 — Agent context (`herald_bridge.py`, `agent_context.py`)

`build_brief` and `build_intake_context` include `reference_links` titles+URLs so HERALD
sees the source docs. No Drive content fetch.

## Data model

- `ContentIntake.reference_links`: JSONField already exists; shape changes from
  `list[str]` → `list[{title,url,type}]`. No migration needed (JSONField). A defensive
  reader tolerates legacy bare-string entries.
- No new models required. Calendar uses existing `composer.Post` + `calendar.CustomCalendarEvent`.

## Files

**Modified:**
- `apps/content_intake/sheets_sync.py` — grid fetch + link extraction
- `apps/content_intake/views.py` — board, row_panel, sync_now, draft_selected, add_to_calendar
- `apps/content_intake/herald_bridge.py` — doc sources in brief
- `apps/content_intake/agent_context.py` — doc links in context
- `config/console_urls.py` — new routes
- `templates/content_intake/board.html` — table + panel shell + bulk bar

**New:**
- `apps/content_intake/intake_calendar.py` — `schedule_intake_item`
- `templates/content_intake/_table.html`, `_row.html`, `_panel.html`, `_doc_chips.html`
- Tests: `test_link_extraction.py`, `test_board_views.py`, `test_intake_calendar.py`, `test_bulk_actions.py`

## Testing

- `_extract_cell_links` / `_link_type`: mocked grid cells with hyperlink, chip, plain text, pdf → correct dicts.
- `_get_sheet_grid` parsing: header + data rows + a chipped doc cell → `reference_links` populated.
- Board view: workspace-scoped (no duplicates from other workspace), sort param applied, login required.
- `row_panel`: renders doc chips for an item with links.
- `sync_now`: POST triggers sync, returns table partial.
- `schedule_intake_item`: creates+links Post, sets scheduled_at + status; skips blocked items.
- `draft_selected`: only eligible items drafted; mocks `request_herald_draft`.
- `build_brief`: includes doc source titles/URLs when reference_links present.

## Out of scope

- Fetching/summarizing full Google Doc *contents* (links-only + titles to AI).
- Drag-and-drop calendar placement.
- Column-level selection (row selection only; "select column" interpreted as sort/filter by column).
- WebSocket true-realtime (poll-based auto-refresh instead).
