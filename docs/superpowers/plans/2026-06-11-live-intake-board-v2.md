# Live Intake Board v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the intake board into a selectable table + detail panel with rendered doc links, one-click and bulk "Draft with HERALD" / "Add to calendar", and live auto-refresh from the Google Sheet.

**Architecture:** Extend `sheets_sync.py` to read the Sheets *grid* API (so hyperlinks + Drive chips are captured into `reference_links`). Rebuild the board view/templates as a workspace-scoped sortable table with an HTMX side panel and a 45s auto-refresh poll. Add `intake_calendar.schedule_intake_item()` to turn an intake row into a scheduled `composer.Post`. Bulk actions post selected IDs.

**Tech Stack:** Django 5.1, HTMX, google-api-python-client, Tailwind. uv at `/Users/macbook/.local/bin/uv`.

**Spec:** `docs/superpowers/specs/2026-06-11-live-intake-board-v2-design.md`

**Test command:** `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest <path> -p no:warnings -q`

---

## File Map

**New:**
- `apps/content_intake/intake_calendar.py` — `schedule_intake_item(intake, when, user)`
- `templates/content_intake/_table.html` — table + auto-refresh poll wrapper
- `templates/content_intake/_row.html` — one table row (checkbox, sortable cells)
- `templates/content_intake/_panel.html` — side-panel detail for one item
- `templates/content_intake/_doc_chips.html` — clickable doc-link chips
- tests: `test_link_extraction.py`, `test_board_views.py`, `test_intake_calendar.py`, `test_bulk_actions.py`

**Modified:**
- `apps/content_intake/sheets_sync.py` — grid fetch + link extraction; write `reference_links` as `[{title,url,type}]`
- `apps/content_intake/views.py` — `board` (table+panel), `row_panel`, `sync_now`, `draft_selected`, `add_to_calendar`
- `apps/content_intake/herald_bridge.py` — append doc sources to the brief
- `apps/content_intake/agent_context.py` — include doc links
- `config/console_urls.py` — new routes
- `templates/content_intake/board.html` — table+panel shell + bulk bar

---

## Task 1: Doc-link extraction helpers

**Files:**
- Modify: `apps/content_intake/sheets_sync.py`
- Test: `apps/content_intake/tests/test_link_extraction.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_link_extraction.py
from apps.content_intake.sheets_sync import _link_type, _extract_cell_links


def test_link_type_classification():
    assert _link_type("https://docs.google.com/document/d/abc/edit") == "gdoc"
    assert _link_type("https://docs.google.com/spreadsheets/d/x") == "gsheet"
    assert _link_type("https://drive.google.com/file/d/y") == "gdrive"
    assert _link_type("https://example.com/report.pdf") == "pdf"
    assert _link_type("https://example.com/page") == "link"


def test_extract_whole_cell_hyperlink():
    cell = {"formattedValue": "Brief Doc", "hyperlink": "https://docs.google.com/document/d/abc/edit"}
    links = _extract_cell_links(cell)
    assert links == [{"title": "Brief Doc", "url": "https://docs.google.com/document/d/abc/edit", "type": "gdoc"}]


def test_extract_drive_chip():
    cell = {
        "formattedValue": "",
        "chipRuns": [
            {"chip": {"richLinkProperties": {"uri": "https://drive.google.com/file/d/xyz", "label": "KALRO data"}}}
        ],
    }
    links = _extract_cell_links(cell)
    assert links == [{"title": "KALRO data", "url": "https://drive.google.com/file/d/xyz", "type": "gdrive"}]


def test_extract_plain_cell_has_no_links():
    assert _extract_cell_links({"formattedValue": "just text"}) == []


def test_extract_falls_back_to_uri_when_no_label():
    cell = {"chipRuns": [{"chip": {"richLinkProperties": {"uri": "https://example.com/x.pdf"}}}]}
    links = _extract_cell_links(cell)
    assert links == [{"title": "https://example.com/x.pdf", "url": "https://example.com/x.pdf", "type": "pdf"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_link_extraction.py -p no:warnings -q`
Expected: FAIL — `ImportError: cannot import name '_link_type'`

- [ ] **Step 3: Implement the helpers**

In `apps/content_intake/sheets_sync.py`, add near the top-level helpers (after the imports/logger):

```python
def _link_type(url: str) -> str:
    """Classify a URL for icon/label rendering."""
    u = (url or "").lower()
    if "docs.google.com/document" in u:
        return "gdoc"
    if "docs.google.com/spreadsheets" in u:
        return "gsheet"
    if "docs.google.com/presentation" in u:
        return "gslides"
    if "drive.google.com" in u:
        return "gdrive"
    if u.endswith(".pdf"):
        return "pdf"
    return "link"


def _extract_cell_links(cell: dict) -> list[dict]:
    """Return [{title, url, type}] from a grid cell's hyperlink + Drive chips.

    Google Sheets values() API drops these; only the grid (includeGridData)
    exposes hyperlink + chipRuns. Deduped by URL, order preserved.
    """
    out: list[dict] = []
    seen: set[str] = set()

    def _add(url: str, title: str | None):
        if not url or url in seen:
            return
        seen.add(url)
        out.append({"title": (title or url), "url": url, "type": _link_type(url)})

    uri = cell.get("hyperlink")
    if uri:
        _add(uri, cell.get("formattedValue"))

    for run in cell.get("chipRuns", []) or []:
        chip = (run.get("chip") or {}).get("richLinkProperties") or {}
        _add(chip.get("uri", ""), chip.get("label"))

    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_link_extraction.py -p no:warnings -q`
Expected: PASS (5 cases)

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/sheets_sync.py apps/content_intake/tests/test_link_extraction.py
git commit -m "feat(intake): cell hyperlink + Drive-chip link extraction helpers"
```

---

## Task 2: Grid fetch → populate reference_links with {title,url,type}

**Files:**
- Modify: `apps/content_intake/sheets_sync.py`
- Test: `apps/content_intake/tests/test_sync.py` (add cases)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_sync.py`:

```python
@pytest.mark.django_db
def test_sync_captures_doc_links_from_grid(workspace):
    """Grid rows with hyperlinks/chips populate reference_links as dicts."""
    from unittest.mock import patch
    from apps.content_intake.models import ContentIntake

    # Header row + one data row; the Notes/Doc cell carries a chip.
    grid = [
        # header (index 0)
        [{"formattedValue": "ID"}, {"formattedValue": "Date"}, {"formattedValue": "By"},
         {"formattedValue": "Pillar"}, {"formattedValue": "Angle"}, {"formattedValue": "Proof"},
         {"formattedValue": "Audience"}, {"formattedValue": "Sensitivity"}, {"formattedValue": "Channel"},
         {"formattedValue": "Campaign"}, {"formattedValue": "Priority"}, {"formattedValue": "Status"},
         {"formattedValue": "Owner"}, {"formattedValue": "Date2"}, {"formattedValue": "Notes"},
         {"formattedValue": "Docs"}],
        # data row GRID-1
        [{"formattedValue": "GRID-1"}, {"formattedValue": "2026-06-11"}, {"formattedValue": "Nduta"},
         {"formattedValue": "Energy"}, {"formattedValue": "Solar"}, {"formattedValue": "IEA"},
         {"formattedValue": "Policy"}, {"formattedValue": "Public-safe"}, {"formattedValue": "LinkedIn"},
         {"formattedValue": ""}, {"formattedValue": "H"}, {"formattedValue": "Idea"},
         {"formattedValue": "Nduta"}, {"formattedValue": ""}, {"formattedValue": "notes"},
         {"formattedValue": "Brief", "hyperlink": "https://docs.google.com/document/d/zzz/edit"}],
    ]
    with patch("apps.content_intake.sheets_sync._get_sheet_grid", return_value=grid):
        sync_sheet_to_intake(workspace)
    item = ContentIntake.objects.get(workspace=workspace, external_id="GRID-1")
    assert item.reference_links == [
        {"title": "Brief", "url": "https://docs.google.com/document/d/zzz/edit", "type": "gdoc"}
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_sync.py::test_sync_captures_doc_links_from_grid -p no:warnings -q`
Expected: FAIL — `_get_sheet_grid` does not exist (AttributeError in patch) or reference_links wrong shape.

- [ ] **Step 3: Add `_get_sheet_grid` and derive rows from it**

In `apps/content_intake/sheets_sync.py`, add a grid fetch that mirrors the existing
auto-detect logic, returning a list of rows where each row is a list of **cell dicts**:

```python
def _get_sheet_grid(sheet_id: str, sheet_range: str) -> list[list[dict]]:
    """Fetch the sheet as grid data (cells with hyperlink/chip info).

    Returns rows of cell dicts (each may have formattedValue, hyperlink, chipRuns).
    Empty list when unconfigured. Auto-corrects the tab name like _get_sheet_rows.
    """
    creds = _build_credentials()
    if creds is None:
        return []
    from googleapiclient.discovery import build
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _fetch(rng: str) -> list[list[dict]]:
        resp = service.spreadsheets().get(
            spreadsheetId=sheet_id, ranges=[rng], includeGridData=True
        ).execute()
        sheets = resp.get("sheets", [])
        if not sheets:
            return []
        data = sheets[0].get("data", [])
        if not data:
            return []
        rows = data[0].get("rowData", [])
        return [r.get("values", []) for r in rows]

    try:
        return _fetch(sheet_range)
    except Exception:
        title = _first_tab_title(service, sheet_id)
        if title:
            try:
                return _fetch(f"'{title}'!{_column_part(sheet_range)}")
            except Exception:
                logger.exception("grid fetch retry failed")
                return []
        logger.exception("grid fetch failed id=%s range=%s", sheet_id, sheet_range)
        return []


def _cell_text(cell: dict) -> str:
    """Visible text of a grid cell."""
    return str(cell.get("formattedValue", "")).strip()
```

Now refactor `sync_sheet_to_intake` to use the grid. Replace the line that fetches rows
(`rows = _get_sheet_rows(effective_sheet_id, effective_range)`) with:

```python
    grid = _get_sheet_grid(effective_sheet_id, effective_range)
    # Derive plain-text rows from the grid so existing column parsing is unchanged.
    rows = [[_cell_text(c) for c in row] for row in grid]
```

Keep everything else (header skip, column map, normalization) the same. Then, where the
row's `reference_links` is currently built (around the `defaults = {...}` dict, key
`"reference_links"`), replace the bare-string list with extracted links from the grid row.
Just before building `defaults`, add:

```python
        # Doc links: scan every cell in this grid row for hyperlinks/chips.
        grid_row = grid[row_index] if row_index < len(grid) else []
        doc_links: list[dict] = []
        _seen_urls: set[str] = set()
        for cell in grid_row:
            for link in _extract_cell_links(cell):
                if link["url"] not in _seen_urls:
                    _seen_urls.add(link["url"])
                    doc_links.append(link)
```

You will need `row_index`. Change the data-row loop from `for row in data_rows:` to
`for row_index, row in enumerate(rows[1:], start=1):` (so `row_index` indexes into `grid`).
Then set the defaults key:

```python
                "reference_links": doc_links,
```

(remove the old comma-split `reference_links` builder).

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_sync.py -p no:warnings -q`
Expected: PASS (existing sync tests + the new one). If existing tests patched `_get_sheet_rows`, update them to patch `_get_sheet_grid` returning cell-dict rows, OR keep `_get_sheet_rows` callers working by having those tests still pass — adjust the mocked tests to the grid shape.

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/sheets_sync.py apps/content_intake/tests/test_sync.py
git commit -m "feat(intake): sync via Sheets grid API — capture doc links into reference_links"
```

---

## Task 3: Doc chips + side panel + row_panel view

**Files:**
- Modify: `apps/content_intake/views.py`
- Create: `templates/content_intake/_doc_chips.html`, `templates/content_intake/_panel.html`
- Modify: `config/console_urls.py`
- Test: `apps/content_intake/tests/test_board_views.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_board_views.py
import pytest
from django.urls import reverse
from apps.content_intake.models import ContentIntake


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    # RBAC middleware resolves request.workspace from the user's membership.
    return client


@pytest.mark.django_db
def test_row_panel_renders_doc_chips(authed, workspace):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="P-1", pillar_theme="Energy", angle="Solar",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
        reference_links=[{"title": "Brief", "url": "https://docs.google.com/document/d/z/edit", "type": "gdoc"}],
    )
    url = reverse("console:intake-row-panel", args=[item.pk])
    resp = authed.get(url)
    assert resp.status_code == 200
    assert b"Brief" in resp.content
    assert b"docs.google.com/document/d/z" in resp.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_board_views.py::test_row_panel_renders_doc_chips -p no:warnings -q`
Expected: FAIL — `NoReverseMatch: 'intake-row-panel'`

- [ ] **Step 3: Create the chip + panel templates**

`templates/content_intake/_doc_chips.html`:

```html
{% if links %}
<div class="flex flex-wrap gap-1.5 mt-1">
  {% for l in links %}
  <a href="{{ l.url }}" target="_blank" rel="noopener"
     class="inline-flex items-center gap-1 rounded border border-stone-200 bg-stone-50 px-2 py-0.5 text-xs text-stone-700 hover:bg-stone-100">
    <span>{% if l.type == 'gdoc' %}📄{% elif l.type == 'gsheet' %}📊{% elif l.type == 'gslides' %}📽️{% elif l.type == 'pdf' %}📕{% elif l.type == 'gdrive' %}🗂️{% else %}🔗{% endif %}</span>
    <span class="truncate max-w-[180px]">{{ l.title }}</span>
  </a>
  {% endfor %}
</div>
{% endif %}
```

`templates/content_intake/_panel.html`:

```html
<div id="intake-panel" class="rounded-lg border border-stone-200 bg-white p-4 text-sm">
  {% if item %}
  <div class="flex items-start justify-between">
    <h3 class="font-semibold text-stone-900">{{ item.pillar_theme }} — {{ item.angle|truncatechars:80 }}</h3>
    <span class="text-[11px] text-stone-400">{{ item.external_id }}</span>
  </div>
  {% if item.proof_point %}<p class="mt-2"><span class="text-stone-400">Proof:</span> {{ item.proof_point }}</p>{% endif %}
  {% if item.target_audience %}<p class="mt-1"><span class="text-stone-400">Audience:</span> {{ item.target_audience }}</p>{% endif %}
  {% if item.notes_raw %}<p class="mt-1 text-stone-600">{{ item.notes_raw }}</p>{% endif %}
  {% if item.reference_links %}
  <div class="mt-3"><span class="text-stone-400 text-xs">Docs:</span>
    {% include "content_intake/_doc_chips.html" with links=item.reference_links %}
  </div>
  {% endif %}
  {% if item.unblock_conditions.all %}
  <div class="mt-3">{% include "content_intake/_condition_checklist.html" with conditions=item.unblock_conditions.all intake=item %}</div>
  {% endif %}
  <div class="mt-4 flex gap-2">
    {% if item.status == "accepted" and item.sensitivity in "public_safe,partner_only" %}
    <form hx-post="{% url 'console:intake-draft-now' item.pk %}" hx-target="#intake-panel" hx-swap="outerHTML">
      {% csrf_token %}
      <button class="rounded bg-indigo-600 text-white px-3 py-1 text-xs font-medium hover:bg-indigo-700">✨ Draft with HERALD</button>
    </form>
    {% endif %}
    <button type="button"
      onclick="document.getElementById('cal-{{ item.pk }}').showModal()"
      class="rounded bg-blue-600 text-white px-3 py-1 text-xs font-medium hover:bg-blue-700">📅 Add to calendar</button>
  </div>
  <dialog id="cal-{{ item.pk }}" class="rounded-lg p-4 backdrop:bg-black/30">
    <form method="dialog"><button class="float-right text-stone-400">✕</button></form>
    <form hx-post="{% url 'console:intake-add-to-calendar' %}" hx-target="#intake-panel" hx-swap="outerHTML" class="space-y-2">
      {% csrf_token %}
      <input type="hidden" name="ids" value="{{ item.pk }}">
      <label class="block text-xs text-stone-500">Schedule date & time</label>
      <input type="datetime-local" name="scheduled_at" required class="rounded border px-2 py-1 text-sm">
      <button class="block rounded bg-blue-600 text-white px-3 py-1 text-xs">Add to calendar</button>
    </form>
  </dialog>
  {% else %}
  <p class="text-stone-400">Select a row to see details.</p>
  {% endif %}
</div>
```

- [ ] **Step 4: Add `row_panel` view**

In `apps/content_intake/views.py`, add (reuse existing imports — `get_object_or_404`, `render`, `login_required`):

```python
@login_required
def row_panel(request, intake_pk):
    item = None
    if request.workspace is not None:
        item = get_object_or_404(
            ContentIntake.objects.prefetch_related("unblock_conditions"),
            pk=intake_pk, workspace=request.workspace,
        )
    return render(request, "content_intake/_panel.html", {"item": item})
```

- [ ] **Step 5: Add the route**

In `config/console_urls.py`, after the draft route:

```python
    path("intake/<uuid:intake_pk>/panel/", intake_views.row_panel, name="intake-row-panel"),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_board_views.py::test_row_panel_renders_doc_chips -p no:warnings -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/content_intake/views.py config/console_urls.py templates/content_intake/_doc_chips.html templates/content_intake/_panel.html apps/content_intake/tests/test_board_views.py
git commit -m "feat(intake): side panel + clickable doc chips (row_panel view)"
```

---

## Task 4: Sortable table + row partials + board shell

**Files:**
- Create: `templates/content_intake/_table.html`, `templates/content_intake/_row.html`
- Modify: `templates/content_intake/board.html`
- Modify: `apps/content_intake/views.py` (board: sort param + partial render)
- Test: `apps/content_intake/tests/test_board_views.py` (add cases)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_board_views.py`:

```python
@pytest.mark.django_db
def test_board_sorts_by_param(authed, workspace):
    ContentIntake.objects.create(workspace=workspace, external_id="A", pillar_theme="Zeta",
        sensitivity="public_safe", status="idea")
    ContentIntake.objects.create(workspace=workspace, external_id="B", pillar_theme="Alpha",
        sensitivity="public_safe", status="idea")
    url = reverse("console:intake-board") + "?sort=pillar"
    resp = authed.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert body.index("Alpha") < body.index("Zeta")


@pytest.mark.django_db
def test_board_partial_returns_table_only(authed, workspace):
    ContentIntake.objects.create(workspace=workspace, external_id="A", pillar_theme="Energy",
        sensitivity="public_safe", status="idea")
    url = reverse("console:intake-board") + "?partial=1"
    resp = authed.get(url)
    assert resp.status_code == 200
    # Partial must NOT include the full page chrome (no <h1 Content Intake)
    assert b"intake-table" in resp.content
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_board_views.py -p no:warnings -q -k "sorts or partial"`
Expected: FAIL — sort not applied / partial returns full page.

- [ ] **Step 3: Update the `board` view**

In `apps/content_intake/views.py`, replace the ordering + render in `board` with sort handling and partial support. After computing `qs` (filters applied), replace the `items = list(...)` line and the final `render` with:

```python
    _SORT_MAP = {
        "pillar": "pillar_theme", "-pillar": "-pillar_theme",
        "status": "status", "-status": "-status",
        "priority": "-priority", "-priority": "priority",
        "owner": "owner_raw", "-owner": "-owner_raw",
        "created": "created_at", "-created": "-created_at",
    }
    sort = request.GET.get("sort", "")
    order = _SORT_MAP.get(sort, "-priority")
    items = list(qs.order_by(order, "-created_at")[:200])
    statuses = ContentIntake.Status.choices
    pillars = (
        ContentIntake.objects.filter(workspace=workspace)
        .exclude(pillar_theme="").values_list("pillar_theme", flat=True).distinct()
    )
    activity = ContentIntake.objects.filter(workspace=workspace).aggregate(
        last_sync_at=Max("last_synced_at"), last_draft_at=Max("herald_drafted_at"),
    )
    ctx = {
        "items": items, "statuses": statuses, "pillars": pillars,
        "status_filter": status_filter, "pillar_filter": pillar_filter,
        "sort": sort,
        "last_sync_at": activity["last_sync_at"], "last_draft_at": activity["last_draft_at"],
    }
    if request.GET.get("partial"):
        return render(request, "content_intake/_table.html", ctx)
    return render(request, "content_intake/board.html", ctx)
```

Also update the early `workspace is None` return to include `"sort": ""` in its context dict (so the template never hits a missing var).

- [ ] **Step 4: Create `_row.html` and `_table.html`**

`templates/content_intake/_row.html`:

```html
<tr class="border-b border-stone-100 hover:bg-stone-50 cursor-pointer"
    hx-get="{% url 'console:intake-row-panel' item.pk %}" hx-target="#intake-panel" hx-swap="outerHTML">
  <td class="px-2 py-2" onclick="event.stopPropagation()">
    <input type="checkbox" name="ids" value="{{ item.pk }}" form="bulk-form" class="row-check">
  </td>
  <td class="px-2 py-2">{{ item.pillar_theme|truncatechars:24 }}</td>
  <td class="px-2 py-2">{{ item.angle|truncatechars:50 }}</td>
  <td class="px-2 py-2">{{ item.owner_raw|default:"—" }}</td>
  <td class="px-2 py-2">{{ item.get_status_display }}</td>
  <td class="px-2 py-2">
    <span class="rounded px-1.5 py-0.5 text-[11px]
      {% if item.sensitivity == 'public_safe' %}bg-green-100 text-green-800
      {% elif item.sensitivity == 'partner_only' %}bg-yellow-100 text-yellow-800
      {% else %}bg-red-100 text-red-800{% endif %}">{{ item.get_sensitivity_display }}</span>
  </td>
  <td class="px-2 py-2 text-stone-400">{% if item.reference_links %}📎 {{ item.reference_links|length }}{% endif %}</td>
</tr>
```

`templates/content_intake/_table.html`:

```html
<div id="intake-table" hx-get="{% url 'console:intake-board' %}?partial=1&sort={{ sort }}&status={{ status_filter }}&pillar={{ pillar_filter }}"
     hx-trigger="every 45s" hx-swap="outerHTML" hx-target="#intake-table">
  <table class="w-full text-sm">
    <thead class="text-left text-stone-500 border-b border-stone-200">
      <tr>
        <th class="px-2 py-2"></th>
        <th class="px-2 py-2"><a href="?sort=pillar">Pillar</a></th>
        <th class="px-2 py-2">Angle</th>
        <th class="px-2 py-2"><a href="?sort=owner">Owner</a></th>
        <th class="px-2 py-2"><a href="?sort=status">Status</a></th>
        <th class="px-2 py-2">Sensitivity</th>
        <th class="px-2 py-2">Docs</th>
      </tr>
    </thead>
    <tbody>
      {% for item in items %}{% include "content_intake/_row.html" with item=item %}{% empty %}
      <tr><td colspan="7" class="px-2 py-6 text-center text-stone-400">No intake items.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
```

- [ ] **Step 5: Rewrite `board.html` as table + panel shell + bulk bar**

`templates/content_intake/board.html`:

```html
{% extends "console/base.html" %}
{% block content %}
<div class="p-6">
  <div class="flex items-center justify-between mb-4">
    <div class="flex items-center gap-3">
      <h1 class="text-2xl font-bold">Content Intake Board</h1>
      {% include "console/_activity_badge.html" with last_sync_at=last_sync_at last_draft_at=last_draft_at %}
    </div>
    <div class="flex items-center gap-2">
      <form method="get" class="flex gap-2">
        <select name="status" class="rounded border px-2 py-1 text-sm">
          <option value="">All statuses</option>
          {% for val, label in statuses %}<option value="{{ val }}" {% if status_filter == val %}selected{% endif %}>{{ label }}</option>{% endfor %}
        </select>
        <select name="pillar" class="rounded border px-2 py-1 text-sm">
          <option value="">All pillars</option>
          {% for p in pillars %}<option value="{{ p }}" {% if pillar_filter == p %}selected{% endif %}>{{ p }}</option>{% endfor %}
        </select>
        <button type="submit" class="rounded bg-stone-700 text-white px-3 py-1 text-sm">Filter</button>
      </form>
      <form hx-post="{% url 'console:intake-sync-now' %}" hx-target="#intake-table" hx-swap="outerHTML">
        {% csrf_token %}
        <button class="rounded bg-green-600 text-white px-3 py-1 text-sm">🔄 Sync now</button>
      </form>
    </div>
  </div>

  <form id="bulk-form" hx-post="{% url 'console:intake-draft-selected' %}" hx-target="#intake-table" hx-swap="outerHTML"
        class="mb-2 flex items-center gap-2 text-sm">
    {% csrf_token %}
    <button type="submit" class="rounded bg-indigo-600 text-white px-3 py-1">✨ Draft selected</button>
    <button type="submit" formaction="{% url 'console:intake-add-to-calendar' %}"
            formmethod="post" class="rounded bg-blue-600 text-white px-3 py-1"
            hx-post="{% url 'console:intake-add-to-calendar' %}" hx-include="#bulk-form">📅 Add selected to calendar</button>
  </form>

  <div class="grid grid-cols-3 gap-4">
    <div class="col-span-2">{% include "content_intake/_table.html" %}</div>
    <div class="col-span-1">{% include "content_intake/_panel.html" with item=None %}</div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 6: Run tests to verify pass**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_board_views.py -p no:warnings -q`
Expected: PASS (panel + sort + partial). The old `test_views.py` board tests should still pass (board still returns 200 with items); if any asserted exact old markup, update them to the new table markup.

- [ ] **Step 7: Commit**

```bash
git add apps/content_intake/views.py templates/content_intake/board.html templates/content_intake/_table.html templates/content_intake/_row.html apps/content_intake/tests/test_board_views.py
git commit -m "feat(intake): sortable workspace-scoped table + side panel + bulk bar shell"
```

---

## Task 5: Sync-now endpoint + live auto-refresh

**Files:**
- Modify: `apps/content_intake/views.py`
- Modify: `config/console_urls.py`
- Test: `apps/content_intake/tests/test_board_views.py` (add case)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_board_views.py`:

```python
@pytest.mark.django_db
def test_sync_now_triggers_sync_and_returns_table(authed, workspace):
    from unittest.mock import patch
    url = reverse("console:intake-sync-now")
    with patch("apps.content_intake.views.sync_sheet_to_intake", return_value={"created": 0}) as m:
        resp = authed.post(url)
    assert resp.status_code == 200
    assert b"intake-table" in resp.content
    m.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_board_views.py::test_sync_now_triggers_sync_and_returns_table -p no:warnings -q`
Expected: FAIL — `NoReverseMatch: 'intake-sync-now'`

- [ ] **Step 3: Add the `sync_now` view**

In `apps/content_intake/views.py`, add the import at top:

```python
from apps.content_intake.sheets_sync import sync_sheet_to_intake
```

and the view:

```python
@login_required
@require_POST
def sync_now(request):
    """Force an immediate sheet pull, then return the refreshed table partial."""
    if request.workspace is not None:
        try:
            sync_sheet_to_intake(request.workspace)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("manual sync_now failed")
    # Re-run the board query path in partial mode by delegating to board().
    request.GET = request.GET.copy()
    request.GET["partial"] = "1"
    return board(request)
```

- [ ] **Step 4: Add the route**

In `config/console_urls.py`:

```python
    path("intake/sync-now/", intake_views.sync_now, name="intake-sync-now"),
```

- [ ] **Step 5: Run test to verify pass**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_board_views.py::test_sync_now_triggers_sync_and_returns_table -p no:warnings -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/content_intake/views.py config/console_urls.py apps/content_intake/tests/test_board_views.py
git commit -m "feat(intake): Sync now button + 45s auto-refresh poll"
```

---

## Task 6: Add-to-calendar (single + bulk)

**Files:**
- Create: `apps/content_intake/intake_calendar.py`
- Modify: `apps/content_intake/views.py`, `config/console_urls.py`
- Test: `apps/content_intake/tests/test_intake_calendar.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_intake_calendar.py
import pytest
from datetime import datetime, timezone as _tz
from apps.content_intake.models import ContentIntake
from apps.content_intake.intake_calendar import schedule_intake_item
from apps.composer.models import Post


@pytest.mark.django_db
def test_schedule_creates_and_links_post(workspace, org_owner):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="C-1", pillar_theme="Energy", angle="Solar story",
        proof_point="IEA", sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    when = datetime(2026, 7, 1, 9, 0, tzinfo=_tz.utc)
    post = schedule_intake_item(item, when, org_owner)
    assert isinstance(post, Post)
    assert post.scheduled_at == when
    item.refresh_from_db()
    assert item.post_id == post.pk
    assert item.status == ContentIntake.Status.SCHEDULED


@pytest.mark.django_db
def test_schedule_skips_blocked_item(workspace, org_owner):
    from apps.content_intake.models import UnblockCondition
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="C-2", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
    )
    UnblockCondition.objects.create(intake=item, condition_type="legal_milestone",
        description="MoU pending", status="open")
    when = datetime(2026, 7, 1, 9, 0, tzinfo=_tz.utc)
    assert schedule_intake_item(item, when, org_owner) is None
    item.refresh_from_db()
    assert item.post_id is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_intake_calendar.py -p no:warnings -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `intake_calendar.py`**

```python
# apps/content_intake/intake_calendar.py
"""Turn an accepted intake item into a scheduled composer.Post on the calendar."""
from __future__ import annotations

import logging

from apps.composer.models import Post

logger = logging.getLogger(__name__)


def schedule_intake_item(intake, when, user):
    """Create (or reuse) a Post for this intake item, scheduled at ``when``.

    Returns the Post, or None if the item is not schedulable (blocked /
    sensitive / unverified). Also drops a CustomCalendarEvent marker so the
    item is visible on the calendar even before a channel is chosen.
    """
    if not intake.is_schedulable:
        return None

    post = intake.post
    if post is None:
        post = Post.objects.create(
            workspace=intake.workspace,
            title=(intake.angle or intake.pillar_theme or intake.external_id)[:255],
            caption=intake.angle or intake.proof_point or "",
        )

    post.scheduled_at = when
    post.save(update_fields=["scheduled_at", "updated_at"])

    intake.post = post
    intake.status = intake.Status.SCHEDULED
    intake.save(update_fields=["post", "status", "updated_at"])

    # Visible calendar marker (best-effort; never blocks scheduling).
    try:
        from apps.calendar.models import CustomCalendarEvent
        CustomCalendarEvent.objects.get_or_create(
            workspace=intake.workspace,
            title=f"📝 {post.title}"[:200],
            start_date=when.date(),
            end_date=when.date(),
            defaults={"created_by": user, "description": f"Intake {intake.external_id}"},
        )
    except Exception:
        logger.exception("calendar marker failed for intake %s", intake.external_id)

    return post
```

- [ ] **Step 4: Add the `add_to_calendar` view**

In `apps/content_intake/views.py`, add:

```python
@login_required
@require_POST
def add_to_calendar(request):
    """Schedule one or many selected intake items. Returns the table partial."""
    from datetime import datetime
    from django.utils import timezone as _tz
    from apps.content_intake.intake_calendar import schedule_intake_item

    ids = request.POST.getlist("ids")
    raw_when = request.POST.get("scheduled_at", "").strip()
    when = None
    if raw_when:
        try:
            parsed = datetime.fromisoformat(raw_when)
            when = parsed if parsed.tzinfo else _tz.make_aware(parsed)
        except ValueError:
            when = None
    if when is None:
        when = _tz.now()

    if request.workspace is not None:
        for item in ContentIntake.objects.filter(pk__in=ids, workspace=request.workspace):
            schedule_intake_item(item, when, request.user)

    request.GET = request.GET.copy()
    request.GET["partial"] = "1"
    return board(request)
```

- [ ] **Step 5: Add the route**

In `config/console_urls.py`:

```python
    path("intake/add-to-calendar/", intake_views.add_to_calendar, name="intake-add-to-calendar"),
```

- [ ] **Step 6: Run tests to verify pass**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_intake_calendar.py -p no:warnings -q`
Expected: PASS (2 cases)

- [ ] **Step 7: Commit**

```bash
git add apps/content_intake/intake_calendar.py apps/content_intake/views.py config/console_urls.py apps/content_intake/tests/test_intake_calendar.py
git commit -m "feat(intake): add-to-calendar — intake item → scheduled Post + calendar marker"
```

---

## Task 7: Bulk draft + doc sources in HERALD brief

**Files:**
- Modify: `apps/content_intake/views.py`, `config/console_urls.py`, `apps/content_intake/herald_bridge.py`
- Test: `apps/content_intake/tests/test_bulk_actions.py`, `apps/content_intake/tests/test_herald_bridge.py` (add case)

- [ ] **Step 1: Write the failing tests**

```python
# apps/content_intake/tests/test_bulk_actions.py
import pytest
from unittest.mock import patch
from django.urls import reverse
from apps.content_intake.models import ContentIntake


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_draft_selected_drafts_each_eligible(authed, workspace):
    a = ContentIntake.objects.create(workspace=workspace, external_id="A", angle="a",
        sensitivity="public_safe", status="accepted")
    b = ContentIntake.objects.create(workspace=workspace, external_id="B", angle="b",
        sensitivity="public_safe", status="accepted")
    url = reverse("console:intake-draft-selected")
    with patch("apps.content_intake.views.request_herald_draft", return_value=True) as m:
        resp = authed.post(url, {"ids": [str(a.pk), str(b.pk)]})
    assert resp.status_code == 200
    assert m.call_count == 2
```

Append to `apps/content_intake/tests/test_herald_bridge.py`:

```python
@pytest.mark.django_db
def test_build_brief_includes_doc_sources(workspace):
    from apps.content_intake.herald_bridge import build_brief
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="D-1", angle="Solar growth",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
        reference_links=[{"title": "IEA Brief", "url": "https://docs.google.com/document/d/z", "type": "gdoc"}],
    )
    brief = build_brief(item)
    assert "IEA Brief" in brief
    assert "docs.google.com/document/d/z" in brief
```

- [ ] **Step 2: Run to verify they fail**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_bulk_actions.py apps/content_intake/tests/test_herald_bridge.py::test_build_brief_includes_doc_sources -p no:warnings -q`
Expected: FAIL — route missing / sources not in brief.

- [ ] **Step 3: Add `draft_selected` view + route**

In `apps/content_intake/views.py` (import already present from Task 5 era: `request_herald_draft` is imported in the file for `draft_now`):

```python
@login_required
@require_POST
def draft_selected(request):
    """Draft every eligible selected intake item with HERALD. Returns table partial."""
    ids = request.POST.getlist("ids")
    if request.workspace is not None:
        for item in ContentIntake.objects.filter(pk__in=ids, workspace=request.workspace):
            try:
                request_herald_draft(item)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("bulk draft failed for %s", item.external_id)
    request.GET = request.GET.copy()
    request.GET["partial"] = "1"
    return board(request)
```

In `config/console_urls.py`:

```python
    path("intake/draft-selected/", intake_views.draft_selected, name="intake-draft-selected"),
```

- [ ] **Step 4: Add doc sources to `build_brief`**

In `apps/content_intake/herald_bridge.py`, in `build_brief`, before the final return, add:

```python
    if intake.reference_links:
        srcs = []
        for l in intake.reference_links:
            if isinstance(l, dict) and l.get("url"):
                srcs.append(f"{l.get('title') or l['url']} ({l['url']})")
            elif isinstance(l, str):  # tolerate legacy bare-string links
                srcs.append(l)
        if srcs:
            parts.append("Sources: " + "; ".join(srcs))
```

(`parts` is the existing list assembled in `build_brief`; this appends a Sources line before `". ".join(...)`.)

- [ ] **Step 5: Run tests to verify pass**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_bulk_actions.py apps/content_intake/tests/test_herald_bridge.py -p no:warnings -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/content_intake/views.py config/console_urls.py apps/content_intake/herald_bridge.py apps/content_intake/tests/test_bulk_actions.py apps/content_intake/tests/test_herald_bridge.py
git commit -m "feat(intake): bulk Draft selected + doc sources in HERALD brief"
```

---

## Task 8: Doc links in agent context

**Files:**
- Modify: `apps/content_intake/agent_context.py`
- Test: `apps/content_intake/tests/test_agent_context.py` (add case)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_agent_context.py`:

```python
@pytest.mark.django_db
def test_context_includes_reference_links(workspace):
    from apps.content_intake.models import ContentIntake
    from apps.content_intake.agent_context import build_intake_context
    ContentIntake.objects.create(
        workspace=workspace, external_id="R-1", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
        reference_links=[{"title": "Brief", "url": "https://docs.google.com/document/d/z", "type": "gdoc"}],
    )
    ctx = build_intake_context(workspace)
    item = next(i for i in ctx["intake_items"] if i["external_id"] == "R-1")
    assert item["reference_links"][0]["url"] == "https://docs.google.com/document/d/z"
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_agent_context.py::test_context_includes_reference_links -p no:warnings -q`
Expected: FAIL — `reference_links` not in the item dict.

- [ ] **Step 3: Add reference_links to the context item dict**

In `apps/content_intake/agent_context.py`, in the loop that builds each item dict (`build_intake_context`), add the key:

```python
            "reference_links": intake.reference_links or [],
```

- [ ] **Step 4: Run test to verify pass**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/tests/test_agent_context.py -p no:warnings -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/agent_context.py apps/content_intake/tests/test_agent_context.py
git commit -m "feat(intake): expose doc reference_links in agent context"
```

---

## Task 9: Full suite + deploy verification

**Files:** none (verification).

- [ ] **Step 1: Run the full content_intake + composer + publisher suites**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/content_intake/ apps/composer/ apps/publisher/ -p no:warnings -q 2>&1 | tail -15`
Expected: all pass. Fix any old `test_views.py` assertions that referenced the pre-v2 board markup.

- [ ] **Step 2: Run the entire suite**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest -p no:warnings -q 2>&1 | tail -8`
Expected: all pass (~860+).

- [ ] **Step 3: Push**

```bash
git push origin main
```

- [ ] **Step 4: Deploy**

```bash
railway link --project 2ee08478-c28d-4e6e-a1d0-bf8d5c871051
railway up --service web
railway up --service worker
```

- [ ] **Step 5: Verify live + backfill doc links**

After deploy settles:
```bash
curl -s -o /dev/null -w "intake:%{http_code}\n" https://web-production-2f84d.up.railway.app/console/intake/
```
Expected: `302`. Then trigger a sync (Sync now button in UI, or shell) and confirm a row's `reference_links` is now populated with `{title,url,type}` dicts.

- [ ] **Step 6: Commit verification note**

```bash
git commit --allow-empty -m "chore: live intake board v2 deployed + verified"
git push origin main
```

---

## Notes for the Operator

- The board now scopes to your active workspace — switch workspace to see that house's items (kills the duplicate rows).
- "Sync now" forces an immediate pull; the table also auto-refreshes every 45s.
- Doc links/chips in the sheet now appear as clickable chips in the side panel and are fed to HERALD as sources.
- "Add to calendar" turns an accepted item into a scheduled Post + a calendar marker.
