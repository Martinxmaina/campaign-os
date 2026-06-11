# Content Workflow Backbone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make intake items flow To Do → In Progress → Done with a Kanban toggle, **manual** HERALD drafting (explicit "Draft with HERALD" click only — never autonomous), a draft-time editable composer Post, edit-opens-existing, and scheduled items visible on the calendar.

**Architecture:** Derive 3 Kanban lanes from the existing `ContentIntake.status` (no migration). A `move_stage` endpoint ONLY changes status (no drafting). The manual `draft_now` action is the sole draft trigger: it drafts via HERALD then creates the editable Post. Reuse the existing `create_post_from_content` helper for draft-time Posts. Fix calendar visibility by rendering channel-less scheduled Posts in the month grid.

**Tech Stack:** Django 5.1, HTMX + Alpine (CSP-safe, native HTML5 drag), agent-service over HTTP. uv at `/Users/macbook/.local/bin/uv`.

**Spec:** `docs/superpowers/specs/2026-06-11-content-workflow-backbone-design.md`

**Test command:** `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <path> -p no:warnings -q`

---

## File Map

**New:**
- `apps/content_intake/draft_post.py` — `ensure_draft_post(intake)`
- `templates/content_intake/board_kanban.html`, `templates/content_intake/_kanban_card.html`
- tests: `test_board_stage.py`, `test_draft_post.py`, `test_move_stage.py`, `test_calendar_visibility.py`

**Modified:**
- `apps/content_intake/models.py` — `board_stage` property + lane sets
- `apps/content_intake/views.py` — `?view=board` branch in `board`, new `move_stage`
- `config/console_urls.py` — `intake-move-stage` route
- `apps/content_intake/intake_calendar.py` — ensure PlatformPosts for connected channels
- `apps/calendar/views.py` — render channel-less scheduled Posts in month grid
- `templates/content_intake/board.html` — Table|Board toggle
- `templates/content_intake/_panel.html` — Edit-in-composer link

---

## Task 1: `board_stage` property

**Files:**
- Modify: `apps/content_intake/models.py`
- Test: `apps/content_intake/tests/test_board_stage.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_board_stage.py
import pytest
from apps.content_intake.models import ContentIntake

@pytest.mark.django_db
@pytest.mark.parametrize("status,expected", [
    ("idea", "todo"), ("accepted", "todo"), ("held", "todo"), ("blocked", "todo"),
    ("drafting", "in_progress"), ("in_review", "in_progress"), ("approved", "in_progress"),
    ("scheduled", "done"), ("published", "done"), ("archived", "done"),
])
def test_board_stage(workspace, status, expected):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id=f"S-{status}", status=status,
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
    )
    assert item.board_stage == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_board_stage.py -p no:warnings -q`
Expected: FAIL — `AttributeError: 'ContentIntake' object has no attribute 'board_stage'`

- [ ] **Step 3: Add the property**

In `apps/content_intake/models.py`, in the `ContentIntake` class (after `is_schedulable`), add:

```python
    _BOARD_IN_PROGRESS = frozenset({"drafting", "in_review", "approved"})
    _BOARD_DONE = frozenset({"scheduled", "published", "archived"})

    @property
    def board_stage(self) -> str:
        """Map the detailed status onto a 3-lane Kanban stage."""
        if self.status in self._BOARD_DONE:
            return "done"
        if self.status in self._BOARD_IN_PROGRESS:
            return "in_progress"
        return "todo"  # idea / accepted / held / blocked / anything unmapped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_board_stage.py -p no:warnings -q`
Expected: PASS (10 cases)

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/models.py apps/content_intake/tests/test_board_stage.py
git commit -m "feat(intake): board_stage property mapping status to 3 Kanban lanes"
```

---

## Task 2: `ensure_draft_post` (draft-time editable Post)

**Files:**
- Create: `apps/content_intake/draft_post.py`
- Test: `apps/content_intake/tests/test_draft_post.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_draft_post.py
from unittest.mock import patch
import pytest
from apps.content_intake.models import ContentIntake
from apps.content_intake.draft_post import ensure_draft_post
from apps.composer.models import Post


def _item(workspace, **kw):
    d = dict(workspace=workspace, external_id="DP-1", angle="Solar growth",
             proof_point="IEA", sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
             status=ContentIntake.Status.DRAFTING, herald_content_id="ci-1")
    d.update(kw)
    return ContentIntake.objects.create(**d)


@pytest.mark.django_db
def test_creates_post_from_content_item(workspace):
    item = _item(workspace)
    content = {"id": "ci-1", "body": "AI-written body about solar.", "title": "Solar"}
    with patch("apps.content_intake.draft_post.safe_get", return_value=content):
        post = ensure_draft_post(item)
    assert isinstance(post, Post)
    assert "AI-written body" in post.caption
    item.refresh_from_db()
    assert item.post_id == post.pk


@pytest.mark.django_db
def test_reuses_existing_post(workspace):
    item = _item(workspace)
    with patch("apps.content_intake.draft_post.safe_get", return_value={"id": "ci-1", "body": "b", "title": "t"}):
        p1 = ensure_draft_post(item)
        p2 = ensure_draft_post(item)
    assert p1.pk == p2.pk


@pytest.mark.django_db
def test_minimal_fallback_when_content_not_ready(workspace):
    item = _item(workspace, herald_content_id="")
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        post = ensure_draft_post(item)
    assert isinstance(post, Post)
    # Falls back to the intake's own angle/proof so the composer has content
    assert "Solar growth" in (post.title + post.caption)
    item.refresh_from_db()
    assert item.post_id == post.pk
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_draft_post.py -p no:warnings -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `draft_post.py`**

```python
# apps/content_intake/draft_post.py
"""Create/return an editable composer Post for an intake item at draft-time.

So 'Edit' opens the existing draft in the full composer instead of only after
approval. Reuses apps.approvals.intake_publish.create_post_from_content for the
content-item path (which also creates PlatformPosts for connected channels).
"""
from __future__ import annotations

from apps.common.safe import safe_get
from apps.approvals.intake_publish import create_post_from_content
from apps.composer.models import Post


def ensure_draft_post(intake):
    """Return the intake's editable Post, creating it from the HERALD draft if needed."""
    if intake.post_id:
        return intake.post

    content = None
    if intake.herald_content_id:
        content = safe_get(f"/content/items/{intake.herald_content_id}", default=None)

    if content:
        return create_post_from_content(content, intake)

    # Content not ready yet — create a minimal Post from the intake itself so the
    # composer has something to open; caption refreshes when the draft lands.
    post = Post.objects.create(
        workspace=intake.workspace,
        title=(intake.angle or intake.pillar_theme or intake.external_id)[:255],
        caption=intake.angle or intake.proof_point or "",
    )
    intake.post = post
    intake.save(update_fields=["post", "updated_at"])
    return post
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_draft_post.py -p no:warnings -q`
Expected: PASS (3 cases)

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/draft_post.py apps/content_intake/tests/test_draft_post.py
git commit -m "feat(intake): ensure_draft_post — draft-time editable composer Post"
```

---

## Task 3: `move_stage` endpoint

**Files:**
- Modify: `apps/content_intake/views.py`, `config/console_urls.py`
- Test: `apps/content_intake/tests/test_move_stage.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_move_stage.py
from unittest.mock import patch
import pytest
from django.urls import reverse
from apps.content_intake.models import ContentIntake


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_move_to_in_progress_only_changes_status_never_drafts(authed, workspace):
    """Moving a card must NOT trigger HERALD — drafting is manual only."""
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="M-1", angle="Solar",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
    )
    url = reverse("console:intake-move-stage", args=[item.pk])
    with patch("apps.content_intake.views.request_herald_draft") as draft:
        resp = authed.post(url, {"to_stage": "in_progress"})
    assert resp.status_code in (200, 204)
    draft.assert_not_called()          # ← stage change must never auto-draft
    item.refresh_from_db()
    assert item.status == ContentIntake.Status.DRAFTING


@pytest.mark.django_db
def test_move_to_todo_reverts_status(authed, workspace):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="M-2", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.DRAFTING,
    )
    url = reverse("console:intake-move-stage", args=[item.pk])
    resp = authed.post(url, {"to_stage": "todo"})
    assert resp.status_code in (200, 204)
    item.refresh_from_db()
    assert item.status == ContentIntake.Status.ACCEPTED


@pytest.mark.django_db
def test_move_blocked_item_to_done_is_rejected(authed, workspace):
    from apps.content_intake.models import UnblockCondition
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="M-3", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.APPROVED,
    )
    UnblockCondition.objects.create(intake=item, condition_type="legal_milestone",
        description="MoU", status="open")
    url = reverse("console:intake-move-stage", args=[item.pk])
    resp = authed.post(url, {"to_stage": "done"})
    item.refresh_from_db()
    assert item.status != ContentIntake.Status.SCHEDULED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_move_stage.py -p no:warnings -q`
Expected: FAIL — `NoReverseMatch: 'intake-move-stage'`

- [ ] **Step 3: Add the `move_stage` view**

In `apps/content_intake/views.py` add the view. `move_stage` ONLY changes status — it must
NOT call `request_herald_draft` or `ensure_draft_post` (drafting is the manual action wired in
Step 6). (`get_object_or_404`, `require_POST`, `HttpResponse`, `login_required` are already imported.)

```python
@login_required
@require_POST
def move_stage(request, intake_pk):
    """Transition an intake item between Kanban lanes (todo|in_progress|done).

    Pure stage change — NEVER drafts. HERALD only runs via the explicit manual
    "Draft with HERALD" action (draft_now).
    """
    if request.workspace is None:
        return HttpResponse(status=403)
    item = get_object_or_404(ContentIntake, pk=intake_pk, workspace=request.workspace)
    to_stage = request.POST.get("to_stage", "")

    if to_stage == "in_progress":
        item.status = ContentIntake.Status.DRAFTING
        item.save(update_fields=["status", "updated_at"])
    elif to_stage == "todo":
        item.status = ContentIntake.Status.ACCEPTED
        item.save(update_fields=["status", "updated_at"])
    elif to_stage == "done" and item.is_schedulable:
        # Mark approved; actual scheduling happens via the add-to-calendar picker.
        item.status = ContentIntake.Status.APPROVED
        item.save(update_fields=["status", "updated_at"])
    # (blocked/sensitive → done is a no-op; the card stays put.)

    request.GET = request.GET.copy()
    request.GET["view"] = "board"
    return board(request)
```

- [ ] **Step 4: Add the route**

In `config/console_urls.py`, after the draft routes:

```python
    path("intake/<uuid:intake_pk>/stage/", intake_views.move_stage, name="intake-move-stage"),
```

- [ ] **Step 5: Wire the MANUAL draft path to create the editable Post**

The manual "Draft with HERALD" action is the only thing that drafts. Extend the existing
`draft_now` and `draft_now_panel` views so that after a successful HERALD draft they also
create the editable composer Post. At the top of `apps/content_intake/views.py` add:

```python
from apps.content_intake.draft_post import ensure_draft_post
```

In `draft_now` (and `draft_now_panel`), right after `ok = request_herald_draft(intake)`, add:

```python
    if ok:
        ensure_draft_post(intake)
```

Add a test to `apps/content_intake/tests/test_move_stage.py`:

```python
@pytest.mark.django_db
def test_manual_draft_now_drafts_and_creates_post(authed, workspace):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="D-1", angle="Solar",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
    )
    url = reverse("console:intake-draft-now", args=[item.pk])
    with patch("apps.content_intake.views.request_herald_draft", return_value=True) as draft, \
         patch("apps.content_intake.views.ensure_draft_post") as ensure:
        resp = authed.post(url)
    assert resp.status_code in (200, 204, 409)
    draft.assert_called_once()
    ensure.assert_called_once()
```

- [ ] **Step 6: Add a confirm to the "Draft with HERALD" button**

In `templates/content_intake/_panel.html`, on the existing Draft-with-HERALD `<form>`/button,
add an `hx-confirm` so drafting is a deliberate click:

```html
    <form hx-post="{% url 'console:intake-draft-now' item.pk %}" hx-target="#intake-panel" hx-swap="outerHTML"
          hx-confirm="Let HERALD draft this with DeepSeek?">
```

(Keep the rest of the form as-is.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_move_stage.py -p no:warnings -q`
Expected: PASS (4 cases — move never drafts; manual draft does). Note: `board(request)` renders the kanban in Task 4; until then it returns the table partial and these tests assert status/calls, not body.

- [ ] **Step 8: Commit**

```bash
git add apps/content_intake/views.py config/console_urls.py templates/content_intake/_panel.html apps/content_intake/tests/test_move_stage.py
git commit -m "feat(intake): move_stage (pure stage change) + manual Draft-with-HERALD creates editable Post"
```

---

## Task 4: Kanban board view + templates + toggle

**Files:**
- Modify: `apps/content_intake/views.py` (`board` gains `?view=board`)
- Create: `templates/content_intake/board_kanban.html`, `templates/content_intake/_kanban_card.html`
- Modify: `templates/content_intake/board.html` (toggle)
- Test: `apps/content_intake/tests/test_board_views.py` (add case)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_board_views.py`:

```python
@pytest.mark.django_db
def test_board_kanban_view_groups_by_stage(authed, workspace):
    from apps.content_intake.models import ContentIntake
    ContentIntake.objects.create(workspace=workspace, external_id="K1", pillar_theme="Energy",
        sensitivity="public_safe", status="idea")          # todo
    ContentIntake.objects.create(workspace=workspace, external_id="K2", pillar_theme="AI",
        sensitivity="public_safe", status="drafting")      # in_progress
    ContentIntake.objects.create(workspace=workspace, external_id="K3", pillar_theme="Agri",
        sensitivity="public_safe", status="scheduled")     # done
    from django.urls import reverse
    resp = authed.get(reverse("console:intake-board") + "?view=board")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "kanban-col-todo" in body
    assert "kanban-col-in_progress" in body
    assert "kanban-col-done" in body
```

(The `authed` fixture already exists in this test module from earlier tasks.)

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_board_views.py::test_board_kanban_view_groups_by_stage -p no:warnings -q`
Expected: FAIL — no kanban columns in response.

- [ ] **Step 3: Branch the `board` view on `?view=board`**

In `apps/content_intake/views.py`, in `board`, after `items` is computed and before the
final `render`, add the kanban branch (keep the partial + table returns intact):

```python
    if request.GET.get("view") == "board":
        lanes = {"todo": [], "in_progress": [], "done": []}
        for it in items:
            lanes[it.board_stage].append(it)
        ctx_board = {**ctx, "lanes": lanes, "view": "board"}
        return render(request, "content_intake/board_kanban.html", ctx_board)
```

(Place this immediately before `if request.GET.get("partial"):`. `ctx` is the context dict already assembled in the view.)

- [ ] **Step 4: Create the kanban templates**

`templates/content_intake/_kanban_card.html`:

```html
<div draggable="true" @dragstart="$event.dataTransfer.setData('text/id','{{ item.pk }}')"
     class="rounded-lg border border-stone-200 bg-white p-3 mb-2 shadow-sm cursor-move"
     hx-get="{% url 'console:intake-row-panel' item.pk %}" hx-target="#intake-panel" hx-swap="outerHTML"
     @click="panelOpen = true">
  <div class="text-xs font-mono text-stone-400">{{ item.external_id }}</div>
  <div class="font-medium text-sm">{{ item.pillar_theme|truncatechars:24 }}</div>
  <div class="text-xs text-stone-600">{{ item.angle|truncatechars:60 }}</div>
  <div class="mt-1 flex items-center gap-1">
    <span class="rounded px-1.5 py-0.5 text-[10px]
      {% if item.sensitivity == 'public_safe' %}bg-green-100 text-green-800
      {% elif item.sensitivity == 'partner_only' %}bg-yellow-100 text-yellow-800
      {% else %}bg-red-100 text-red-800{% endif %}">{{ item.get_sensitivity_display }}</span>
    {% if item.reference_links %}<span class="text-[10px] text-stone-400">📎 {{ item.reference_links|length }}</span>{% endif %}
  </div>
</div>
```

`templates/content_intake/board_kanban.html`:

```html
{% extends "console/base.html" %}
{% block content %}
<div class="p-6" x-data="{ panelOpen: false }">
  <div class="flex items-center justify-between mb-4">
    <h1 class="text-2xl font-bold">Content Intake Board</h1>
    <div class="flex gap-2 text-sm">
      <a href="?" class="rounded border px-3 py-1">Table</a>
      <a href="?view=board" class="rounded bg-stone-700 text-white px-3 py-1">Board</a>
    </div>
  </div>
  <div class="grid grid-cols-3 gap-4">
    {% for stage, label in lanes_labels %}
    <div id="kanban-col-{{ stage }}"
         @dragover.prevent @drop="
           const id = $event.dataTransfer.getData('text/id');
           htmx.ajax('POST', '/console/intake/'+id+'/stage/', {values:{to_stage:'{{ stage }}', csrfmiddlewaretoken:'{{ csrf_token }}'}, target:'body', swap:'none'}).then(()=>window.location.reload());"
         class="rounded-lg bg-stone-50 border border-stone-200 p-3 min-h-[200px]">
      <h3 class="text-sm font-semibold text-stone-500 mb-2">{{ label }}</h3>
      {% for item in lanes|dictlookup:stage %}{% include "content_intake/_kanban_card.html" with item=item %}{% endfor %}
    </div>
    {% endfor %}
  </div>
  <div x-show="panelOpen" x-cloak @keydown.escape.window="panelOpen=false" class="fixed inset-0 z-40" style="display:none">
    <div class="absolute inset-0 bg-black/30" @click="panelOpen=false"></div>
    <div class="absolute inset-y-0 right-0 w-full max-w-md bg-white shadow-xl overflow-y-auto p-4" @click.stop>
      <button type="button" @click="panelOpen=false" class="float-right text-stone-400 text-lg">✕</button>
      {% include "content_intake/_panel.html" with item=None %}
    </div>
  </div>
</div>
{% endblock %}
```

The template needs `lanes_labels` (ordered) and a `dictlookup` filter. In the kanban branch
in `board` (Step 3), pass labels explicitly and restructure to avoid a custom filter:

```python
        ordered = [("todo", "To Do"), ("in_progress", "In Progress"), ("done", "Done")]
        ctx_board = {**ctx, "lanes_labels": ordered,
                     "lane_todo": lanes["todo"], "lane_in_progress": lanes["in_progress"],
                     "lane_done": lanes["done"], "view": "board"}
        return render(request, "content_intake/board_kanban.html", ctx_board)
```

And in `board_kanban.html` replace the inner card loop with explicit lanes (no custom filter):

```html
      {% if stage == 'todo' %}{% for item in lane_todo %}{% include "content_intake/_kanban_card.html" with item=item %}{% endfor %}
      {% elif stage == 'in_progress' %}{% for item in lane_in_progress %}{% include "content_intake/_kanban_card.html" with item=item %}{% endfor %}
      {% else %}{% for item in lane_done %}{% include "content_intake/_kanban_card.html" with item=item %}{% endfor %}{% endif %}
```

- [ ] **Step 5: Add the Table|Board toggle to the table view**

In `templates/content_intake/board.html`, in the header actions `<div class="flex items-center gap-2">`, add before the filter form:

```html
      <div class="flex gap-1 text-sm">
        <a href="?" class="rounded bg-stone-700 text-white px-3 py-1">Table</a>
        <a href="?view=board" class="rounded border px-3 py-1">Board</a>
      </div>
```

- [ ] **Step 6: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_board_views.py -p no:warnings -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/content_intake/views.py templates/content_intake/board_kanban.html templates/content_intake/_kanban_card.html templates/content_intake/board.html apps/content_intake/tests/test_board_views.py
git commit -m "feat(intake): Kanban board view + Table|Board toggle + drag-to-stage"
```

---

## Task 5: Edit-in-composer link

**Files:**
- Modify: `templates/content_intake/_panel.html`
- Test: `apps/content_intake/tests/test_board_views.py` (add case)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_board_views.py`:

```python
@pytest.mark.django_db
def test_panel_shows_edit_link_when_post_exists(authed, workspace):
    from apps.content_intake.models import ContentIntake
    from apps.composer.models import Post
    post = Post.objects.create(workspace=workspace, title="t", caption="c")
    item = ContentIntake.objects.create(workspace=workspace, external_id="E1", angle="x",
        sensitivity="public_safe", status="drafting", post=post)
    from django.urls import reverse
    resp = authed.get(reverse("console:intake-row-panel", args=[item.pk]))
    assert resp.status_code == 200
    assert f"/workspace/{workspace.pk}/compose/{post.pk}/".encode() in resp.content
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_board_views.py::test_panel_shows_edit_link_when_post_exists -p no:warnings -q`
Expected: FAIL — no compose link in panel.

- [ ] **Step 3: Add the Edit link to the panel**

In `templates/content_intake/_panel.html`, inside the actions `<div class="mt-4 flex gap-2">`, add:

```html
    {% if item.post_id %}
    <a href="{% url 'composer:compose_edit' workspace_id=item.workspace_id post_id=item.post_id %}"
       class="rounded bg-stone-700 text-white px-3 py-1 text-xs font-medium hover:bg-stone-800">✎ Edit in composer</a>
    {% endif %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_board_views.py::test_panel_shows_edit_link_when_post_exists -p no:warnings -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add templates/content_intake/_panel.html apps/content_intake/tests/test_board_views.py
git commit -m "feat(intake): Edit-in-composer link on the detail panel"
```

---

## Task 6: Calendar renders channel-less scheduled Posts

**Files:**
- Modify: `apps/calendar/views.py`
- Test: `apps/content_intake/tests/test_calendar_visibility.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_calendar_visibility.py
from datetime import timedelta
import pytest
from django.urls import reverse
from django.utils import timezone
from apps.composer.models import Post


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_channelless_scheduled_post_shows_on_calendar(authed, workspace):
    when = timezone.now() + timedelta(days=1)
    post = Post.objects.create(workspace=workspace, title="Planning item",
                               caption="x", scheduled_at=when)
    # No PlatformPost — channel-less.
    url = reverse("calendar:index", args=[workspace.pk]) + f"?year={when.year}&month={when.month}"
    resp = authed.get(url)
    assert resp.status_code == 200
    assert b"Planning item" in resp.content
```

(Confirm the calendar URL name with `grep -n "name=" apps/calendar/urls.py`; if it is not
`calendar:index`, use the actual month-view name.)

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_calendar_visibility.py -p no:warnings -q`
Expected: FAIL — channel-less post not in the month grid.

- [ ] **Step 3: Render channel-less scheduled Posts in the month grid**

In `apps/calendar/views.py::calendar_view`, find the block that builds `posts_by_date` from
`platform_posts` (around line 159: `for pp in platform_posts:`). Immediately after that loop,
add a second loop over channel-less scheduled Posts in the visible range:

```python
    # Channel-less scheduled Posts (e.g. intake "Add to calendar" before a channel
    # is connected) aren't represented by any PlatformPost, so render them directly.
    first_day, last_day = weeks[0][0], weeks[-1][6]
    channelless = (
        Post.objects.for_workspace(workspace.id)
        .filter(scheduled_at__date__gte=first_day, scheduled_at__date__lte=last_day,
                platform_posts__isnull=True)
        .distinct()
    )
    for post in channelless:
        posts_by_date[post.scheduled_at.astimezone(display_tz).date()].append(post)
```

(`weeks`, `posts_by_date`, `display_tz`, and `Post` are already in scope in `calendar_view`;
`Post` is imported at the top of the module. The calendar day template already iterates
`day.posts` and renders each item's title, so a `Post` object renders alongside `PlatformPost`s.)

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_calendar_visibility.py -p no:warnings -q`
Expected: PASS. If the day template accesses PlatformPost-only attributes and errors on a
plain Post, guard those template accesses with `{% if post.social_account %}` so a bare Post
renders its title without per-platform fields.

- [ ] **Step 5: Run the calendar suite for regressions**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/calendar/ -p no:warnings -q 2>&1 | tail -5`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/calendar/views.py apps/content_intake/tests/test_calendar_visibility.py
git commit -m "fix(calendar): render channel-less scheduled Posts in the month grid (intake add-to-calendar now visible)"
```

---

## Task 7: Full suite + deploy verification

**Files:** none (verification).

- [ ] **Step 1: Full suite**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest -p no:warnings -q 2>&1 | tail -12`
Expected: all pass. Fix any calendar template assertions broken by rendering a bare Post.

- [ ] **Step 2: Push**

```bash
git push origin main
```

- [ ] **Step 3: Deploy**

```bash
railway link --project 2ee08478-c28d-4e6e-a1d0-bf8d5c871051
railway up --service web
railway up --service worker
```

- [ ] **Step 4: Verify live**

```bash
until [ "$(curl -s -o /dev/null -w '%{http_code}' https://web-production-2f84d.up.railway.app/console/intake/?view=board)" != "000" ]; do sleep 8; done
curl -s -o /dev/null -w "board:%{http_code}\n" "https://web-production-2f84d.up.railway.app/console/intake/?view=board"
```
Expected: `302` (redirect to login = route exists).

- [ ] **Step 5: Commit verification note**

```bash
git commit --allow-empty -m "chore: content workflow backbone deployed + verified"
git push origin main
```

---

## Notes for the Operator

- Intake board now has a **Table | Board** toggle. The Board view has To Do / In Progress / Done — drag a card to change stage. Dragging only re-stages; it never drafts.
- **Drafting is manual:** click **"Draft with HERALD"** on an item (confirm dialog) to have HERALD draft it on DeepSeek and create an editable composer Post. You own the idea and decide when the agent writes.
- Click **Edit in composer** on any drafted item to open the full editor.
- **Add to calendar** items now appear on the content calendar even before a channel is connected.
- Next sub-projects: approval owner-routing (#4), Resend reminders (#7), analytics (#6), pipeline (#9).
