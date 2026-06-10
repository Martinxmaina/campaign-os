# Bridge the Two Brains — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Django ContentIntake → HERALD drafting → console approval → auto-created publishable Post, and expose the new surfaces in the sidebar.

**Architecture:** Django pushes each accepted intake item to the agent-service's existing `POST /agents/herald/draft` using the item as the `brief`. Approving the resulting draft in the console auto-creates a Django Post that flows through the existing gate → publisher. No new storage on agent-service.

**Tech Stack:** Django 5.1, Celery + Redis, httpx (via `apps/common/agent_client.py`), HTMX, agent-service over Bearer-token HTTP.

**Spec:** `docs/superpowers/specs/2026-06-10-bridge-two-brains-design.md`

**Run tests:** `uv run pytest <path> -q` (uv at `/Users/macbook/.local/bin/uv` if not on PATH)

---

## File Map

**New:**
- `apps/content_intake/sector_map.py` — pillar_theme → sector
- `apps/content_intake/herald_bridge.py` — brief assembly + draft request
- `apps/content_intake/migrations/0002_herald_link_fields.py` — generated
- `templates/console/_activity_badge.html` — last sync/draft indicator
- tests: `test_sector_map.py`, `test_herald_bridge.py`, `test_herald_trigger.py`, `test_approve_creates_post.py`

**Modified:**
- `apps/content_intake/models.py` — `herald_content_id`, `herald_drafted_at`
- `apps/content_intake/tasks.py` — `request_herald_drafts_for_workspace` + call from sync + cache timestamps
- `apps/content_intake/views.py` — `draft_now` view
- `config/console_urls.py` — draft-now route
- `templates/content_intake/_card.html` — Draft now button
- `apps/approvals/console_views.py` — approve → create Post
- `templates/base.html` — sidebar Intake + News + activity badge
- `config/settings/base.py` + `.env.example` — twitter credential slot

---

## Task 1: Sector mapping

**Files:**
- Create: `apps/content_intake/sector_map.py`
- Test: `apps/content_intake/tests/test_sector_map.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_sector_map.py
import pytest
from apps.content_intake.sector_map import map_pillar_to_sector

@pytest.mark.parametrize("raw,expected", [
    ("energy", "energy"),
    ("Energy", "energy"),
    ("Power & Energy", "energy"),
    ("agribusiness", "agribusiness"),
    ("Agriculture", "agribusiness"),
    ("Food systems", "agribusiness"),
    ("ai", "ai"),
    ("AI", "ai"),
    ("AI 10Bn", "ai"),
    ("Artificial Intelligence", "ai"),
    ("something random", "general"),
    ("", "general"),
])
def test_map_pillar_to_sector(raw, expected):
    assert map_pillar_to_sector(raw) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/content_intake/tests/test_sector_map.py -q`
Expected: FAIL — `ModuleNotFoundError: apps.content_intake.sector_map`

- [ ] **Step 3: Implement**

```python
# apps/content_intake/sector_map.py
"""Map a free-text pillar/theme string to a canonical agent-service sector.

The agent-service accepts only: energy | agribusiness | ai | general.
"""
import re

_RULES = [
    (re.compile(r"energy|power|electri|renewable|solar|grid", re.I), "energy"),
    (re.compile(r"agri|farm|food|crop|kalro|livestock", re.I), "agribusiness"),
    (re.compile(r"\bai\b|artificial intelligence|10bn|machine learning", re.I), "ai"),
]


def map_pillar_to_sector(pillar_theme: str) -> str:
    text = (pillar_theme or "").strip()
    for pattern, sector in _RULES:
        if pattern.search(text):
            return sector
    return "general"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/content_intake/tests/test_sector_map.py -q`
Expected: PASS (12 cases)

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/sector_map.py apps/content_intake/tests/test_sector_map.py
git commit -m "feat(intake): pillar_theme → agent-service sector mapping"
```

---

## Task 2: ContentIntake HERALD-link fields

**Files:**
- Modify: `apps/content_intake/models.py`
- Create: `apps/content_intake/migrations/0002_herald_link_fields.py` (generated)
- Test: `apps/content_intake/tests/test_models.py` (add cases)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_models.py`:

```python
@pytest.mark.django_db
def test_herald_link_fields_default_empty(workspace):
    from apps.content_intake.models import ContentIntake
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="HL-1",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    assert item.herald_content_id == ""
    assert item.herald_drafted_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/content_intake/tests/test_models.py::test_herald_link_fields_default_empty -q`
Expected: FAIL — `AttributeError: 'ContentIntake' object has no attribute 'herald_content_id'`

- [ ] **Step 3: Add fields to the model**

In `apps/content_intake/models.py`, in the `ContentIntake` class after the `post` field, add:

```python
    # HERALD drafting linkage (agent-service content_item)
    herald_content_id = models.CharField(
        max_length=64, blank=True, default="",
        help_text="agent-service content_item id produced by HERALD from this intake.",
    )
    herald_drafted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When HERALD last drafted this item (idempotency guard).",
    )
```

- [ ] **Step 4: Generate and run migration**

Run:
```bash
uv run python manage.py makemigrations content_intake --name herald_link_fields
uv run python manage.py migrate
```
Expected: `0002_herald_link_fields ... OK`

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest apps/content_intake/tests/test_models.py::test_herald_link_fields_default_empty -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/content_intake/models.py apps/content_intake/migrations/0002_herald_link_fields.py apps/content_intake/tests/test_models.py
git commit -m "feat(intake): add herald_content_id + herald_drafted_at link fields"
```

---

## Task 3: HERALD bridge (brief assembly + draft request)

**Files:**
- Create: `apps/content_intake/herald_bridge.py`
- Test: `apps/content_intake/tests/test_herald_bridge.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_herald_bridge.py
from unittest.mock import patch
import pytest
from apps.content_intake.herald_bridge import build_brief, request_herald_draft
from apps.content_intake.models import ContentIntake


def _make(workspace, **kw):
    defaults = dict(
        workspace=workspace, external_id="BR-1",
        pillar_theme="Energy", angle="Solar grows fast in EA",
        proof_point="IEA 2024", target_audience="Policymakers",
        channel_targets=[{"platform": "linkedin", "account": "waiis"}],
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    defaults.update(kw)
    return ContentIntake.objects.create(**defaults)


@pytest.mark.django_db
def test_build_brief_assembles_fields(workspace):
    item = _make(workspace)
    brief = build_brief(item)
    assert "Solar grows fast" in brief
    assert "IEA 2024" in brief
    assert "Policymakers" in brief
    assert "linkedin" in brief


@pytest.mark.django_db
def test_build_brief_skips_empty_fields(workspace):
    item = _make(workspace, proof_point="", target_audience="", channel_targets=[])
    brief = build_brief(item)
    assert brief == "Solar grows fast in EA"


@pytest.mark.django_db
def test_request_draft_skips_private_hold(workspace):
    item = _make(workspace, sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD)
    with patch("apps.content_intake.herald_bridge.agent_post") as m:
        result = request_herald_draft(item)
    assert result is False
    m.assert_not_called()


@pytest.mark.django_db
def test_request_draft_skips_non_accepted(workspace):
    item = _make(workspace, status=ContentIntake.Status.IDEA)
    with patch("apps.content_intake.herald_bridge.agent_post") as m:
        assert request_herald_draft(item) is False
    m.assert_not_called()


@pytest.mark.django_db
def test_request_draft_skips_already_drafted(workspace):
    from django.utils import timezone
    item = _make(workspace, herald_drafted_at=timezone.now())
    with patch("apps.content_intake.herald_bridge.agent_post") as m:
        assert request_herald_draft(item) is False
    m.assert_not_called()


@pytest.mark.django_db
def test_request_draft_success_sets_fields(workspace):
    item = _make(workspace)
    fake = {"variant_group": "vg-1", "proposals": [{"content_id": "ci-123"}]}
    with patch("apps.content_intake.herald_bridge.agent_post", return_value=fake) as m:
        assert request_herald_draft(item) is True
    m.assert_called_once()
    item.refresh_from_db()
    assert item.herald_content_id == "ci-123"
    assert item.herald_drafted_at is not None
    assert item.status == ContentIntake.Status.DRAFTING


@pytest.mark.django_db
def test_request_draft_failure_leaves_unchanged(workspace):
    item = _make(workspace)
    with patch("apps.content_intake.herald_bridge.agent_post", side_effect=Exception("boom")):
        assert request_herald_draft(item) is False
    item.refresh_from_db()
    assert item.herald_content_id == ""
    assert item.herald_drafted_at is None
    assert item.status == ContentIntake.Status.ACCEPTED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/content_intake/tests/test_herald_bridge.py -q`
Expected: FAIL — `ModuleNotFoundError: apps.content_intake.herald_bridge`

- [ ] **Step 3: Implement**

```python
# apps/content_intake/herald_bridge.py
"""Bridge: push an accepted ContentIntake item to HERALD for drafting.

Django calls the agent-service's existing POST /agents/herald/draft with the
intake item rendered as the `brief`. No new storage on agent-service.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.common.agent_client import agent_post
from apps.content_intake.models import ContentIntake
from apps.content_intake.sector_map import map_pillar_to_sector

logger = logging.getLogger(__name__)

_AGENT_VISIBLE = frozenset(["public_safe", "partner_only"])


def build_brief(intake: ContentIntake) -> str:
    """Render an intake item into a HERALD brief string."""
    parts = [intake.angle.strip()] if intake.angle else []
    if intake.proof_point:
        parts.append(f"Proof: {intake.proof_point.strip()}")
    if intake.target_audience:
        parts.append(f"Audience: {intake.target_audience.strip()}")
    if intake.channel_targets:
        chans = ", ".join(
            t.get("platform", "") for t in intake.channel_targets if t.get("platform")
        )
        if chans:
            parts.append(f"Channels: {chans}")
    return ". ".join(p for p in parts if p)


def _is_eligible(intake: ContentIntake) -> bool:
    if intake.status != ContentIntake.Status.ACCEPTED:
        return False
    if intake.sensitivity not in _AGENT_VISIBLE:
        return False
    if intake.herald_drafted_at is not None:
        return False
    if not intake.is_schedulable:
        return False
    return True


def request_herald_draft(intake: ContentIntake) -> bool:
    """Ask HERALD to draft this intake item. Returns True on success.

    Idempotent: items already drafted (herald_drafted_at set) are skipped.
    Failure leaves the item unchanged so the next sync retries.
    """
    if not _is_eligible(intake):
        return False

    sector = map_pillar_to_sector(intake.pillar_theme)
    brief = build_brief(intake)

    try:
        result = agent_post(
            "/agents/herald/draft",
            {"sector": sector, "brief": brief, "count": 1},
        )
    except Exception:
        logger.exception("HERALD draft request failed for intake=%s", intake.external_id)
        return False

    content_id = ""
    proposals = result.get("proposals") if isinstance(result, dict) else None
    if proposals and isinstance(proposals, list) and isinstance(proposals[0], dict):
        content_id = str(proposals[0].get("content_id", ""))

    intake.herald_content_id = content_id
    intake.herald_drafted_at = timezone.now()
    intake.status = ContentIntake.Status.DRAFTING
    intake.save(update_fields=["herald_content_id", "herald_drafted_at", "status", "updated_at"])
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/content_intake/tests/test_herald_bridge.py -q`
Expected: PASS (7 cases)

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/herald_bridge.py apps/content_intake/tests/test_herald_bridge.py
git commit -m "feat(intake): HERALD bridge — brief assembly + eligibility-gated draft request"
```

---

## Task 4: Auto-trigger drafts on sync + activity timestamps

**Files:**
- Modify: `apps/content_intake/tasks.py`
- Test: `apps/content_intake/tests/test_herald_trigger.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_herald_trigger.py
from unittest.mock import patch
import pytest
from apps.content_intake.models import ContentIntake
from apps.content_intake.tasks import request_herald_drafts_for_workspace


@pytest.mark.django_db
def test_drafts_only_eligible_items(workspace):
    ContentIntake.objects.create(
        workspace=workspace, external_id="A",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="a",
    )
    ContentIntake.objects.create(
        workspace=workspace, external_id="B",
        sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
        status=ContentIntake.Status.ACCEPTED, angle="b",
    )
    ContentIntake.objects.create(
        workspace=workspace, external_id="C",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.IDEA, angle="c",
    )
    with patch("apps.content_intake.tasks.request_herald_draft", return_value=True) as m:
        result = request_herald_drafts_for_workspace(str(workspace.pk))
    # Only item A is eligible (accepted + public_safe)
    assert m.call_count == 1
    assert result["drafted"] == 1


@pytest.mark.django_db
def test_sets_last_draft_cache(workspace):
    from django.core.cache import cache
    ContentIntake.objects.create(
        workspace=workspace, external_id="A",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="a",
    )
    with patch("apps.content_intake.tasks.request_herald_draft", return_value=True):
        request_herald_drafts_for_workspace(str(workspace.pk))
    assert cache.get(f"intake:last_draft:{workspace.pk}") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/content_intake/tests/test_herald_trigger.py -q`
Expected: FAIL — `ImportError: cannot import name 'request_herald_drafts_for_workspace'`

- [ ] **Step 3: Implement the task + wire into sync**

In `apps/content_intake/tasks.py`, add at the end:

```python
@shared_task
def request_herald_drafts_for_workspace(workspace_id: str):
    """Ask HERALD to draft every eligible accepted intake item in a workspace."""
    from django.core.cache import cache
    from django.utils import timezone

    from apps.content_intake.herald_bridge import request_herald_draft
    from apps.content_intake.models import ContentIntake

    eligible = ContentIntake.objects.filter(
        workspace_id=workspace_id,
        status=ContentIntake.Status.ACCEPTED,
        sensitivity__in=["public_safe", "partner_only"],
        herald_drafted_at__isnull=True,
    )
    drafted = 0
    for item in eligible:
        if request_herald_draft(item):
            drafted += 1
    cache.set(f"intake:last_draft:{workspace_id}", timezone.now().isoformat(), timeout=None)
    return {"drafted": drafted}
```

Then in `sync_intake_sheet`, change the success path. Replace:

```python
    try:
        return sync_sheet_to_intake(workspace)
    except Exception as exc:
        raise self.retry(exc=exc)
```

with:

```python
    from django.core.cache import cache
    from django.utils import timezone

    try:
        result = sync_sheet_to_intake(workspace)
    except Exception as exc:
        raise self.retry(exc=exc)

    cache.set(f"intake:last_sync:{workspace_id}", timezone.now().isoformat(), timeout=None)
    # Kick off HERALD drafting for any newly-accepted items (auto-on-sync).
    request_herald_drafts_for_workspace.delay(str(workspace.pk))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/content_intake/tests/test_herald_trigger.py -q`
Expected: PASS (2 cases)

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/tasks.py apps/content_intake/tests/test_herald_trigger.py
git commit -m "feat(intake): auto-trigger HERALD drafts on sync + activity timestamps"
```

---

## Task 5: "Draft now" manual button

**Files:**
- Modify: `apps/content_intake/views.py`
- Modify: `config/console_urls.py`
- Modify: `templates/content_intake/_card.html`
- Test: `apps/content_intake/tests/test_views.py` (add case)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_draft_now_calls_herald(authenticated_client, intake_item):
    from django.urls import reverse
    from unittest.mock import patch
    intake_item.status = "accepted"
    intake_item.sensitivity = "public_safe"
    intake_item.save()
    url = reverse("console:intake-draft-now", args=[intake_item.pk])
    with patch("apps.content_intake.views.request_herald_draft", return_value=True) as m:
        resp = authenticated_client.post(url)
    assert resp.status_code in (200, 204, 302)
    m.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/content_intake/tests/test_views.py::test_draft_now_calls_herald -q`
Expected: FAIL — `NoReverseMatch: 'intake-draft-now'`

- [ ] **Step 3: Add the view**

In `apps/content_intake/views.py`, add the import at top:

```python
from apps.content_intake.herald_bridge import request_herald_draft
```

and add the view:

```python
@login_required
@require_POST
@workspace_required
def draft_now(request, intake_pk):
    """Manually ask HERALD to draft a single intake item."""
    intake = get_object_or_404(ContentIntake, pk=intake_pk, workspace=request.workspace)
    ok = request_herald_draft(intake)
    if request.headers.get("HX-Request"):
        return render(request, "content_intake/_card.html", {"item": intake})
    return HttpResponse(status=204 if ok else 409)
```

(If `get_object_or_404`, `HttpResponse`, `require_POST`, or `workspace_required` are not already imported in this file, add them — match the imports already used by the `board`/`close_condition` views.)

- [ ] **Step 4: Add the route**

In `config/console_urls.py`, in `urlpatterns` after the intake board routes, add:

```python
    path("intake/<uuid:intake_pk>/draft/", intake_views.draft_now, name="intake-draft-now"),
```

- [ ] **Step 5: Add the button to the card**

In `templates/content_intake/_card.html`, inside the card body, add (only show for accepted public/partner items):

```html
  {% if item.status == "accepted" and item.sensitivity in "public_safe,partner_only" %}
  <form hx-post="{% url 'console:intake-draft-now' item.pk %}" hx-target="closest .rounded-lg" hx-swap="outerHTML" class="mt-2">
    {% csrf_token %}
    <button type="submit" class="rounded bg-indigo-600 text-white px-3 py-1 text-xs font-medium hover:bg-indigo-700">
      ✨ Draft with HERALD
    </button>
  </form>
  {% endif %}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest apps/content_intake/tests/test_views.py::test_draft_now_calls_herald -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/content_intake/views.py config/console_urls.py templates/content_intake/_card.html apps/content_intake/tests/test_views.py
git commit -m "feat(intake): Draft with HERALD button on intake board cards"
```

---

## Task 6: Sidebar — Intake + News links + activity badge

**Files:**
- Create: `templates/console/_activity_badge.html`
- Modify: `templates/base.html`

- [ ] **Step 1: Create the activity badge partial**

`templates/console/_activity_badge.html`:

```html
{% load tz %}
<div class="px-3 py-1 text-[10px] text-stone-400 leading-tight">
  {% if last_sync_at %}<div>Sheet synced: {{ last_sync_at }}</div>{% endif %}
  {% if last_draft_at %}<div>HERALD drafted: {{ last_draft_at }}</div>{% endif %}
</div>
```

- [ ] **Step 2: Add nav links to base.html**

In `templates/base.html`, in the Intelligence section, after the Brain `<a>` block (around line 632), add:

```html
                <a href="/console/intake/" class="mb-1 sidebar-nav-item {% if request.resolver_match.url_name == 'intake-board' and request.resolver_match.app_name == 'console' %}active{% endif %}">
                    <svg class="flex-shrink-0" width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11H3v10h6V11z"/><path d="M21 3h-6v18h6V3z"/><path d="M15 7H9v14h6V7z"/></svg>
                    <span class="sidebar-nav-label">Intake</span>
                </a>
                <a href="/console/news" class="mb-1 sidebar-nav-item {% if request.resolver_match.url_name == 'news' and request.resolver_match.app_name == 'console' %}active{% endif %}">
                    <svg class="flex-shrink-0" width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 002-2V4a2 2 0 00-2-2H8a2 2 0 00-2 2v16a2 2 0 01-2 2zm0 0a2 2 0 01-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8z"/></svg>
                    <span class="sidebar-nav-label">News</span>
                </a>
```

- [ ] **Step 3: Manually verify rendering**

Run:
```bash
uv run python manage.py shell -c "from django.template.loader import get_template; get_template('base.html'); get_template('console/_activity_badge.html'); print('templates load OK')"
```
Expected: `templates load OK`

- [ ] **Step 4: Verify URLs resolve**

Run:
```bash
uv run python manage.py shell -c "from django.urls import reverse; print(reverse('console:intake-board')); print(reverse('console:news'))"
```
Expected: `/console/intake/` and `/console/news`

- [ ] **Step 5: Commit**

```bash
git add templates/base.html templates/console/_activity_badge.html
git commit -m "feat(console): sidebar Intake + News links + activity badge"
```

---

## Task 7: Approve → auto-create publishable Post

**Files:**
- Modify: `apps/approvals/console_views.py`
- Create: `apps/approvals/intake_publish.py`
- Test: `apps/approvals/tests/test_approve_creates_post.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/approvals/tests/test_approve_creates_post.py
from unittest.mock import patch
import pytest
from apps.content_intake.models import ContentIntake
from apps.composer.models import Post
from apps.approvals.intake_publish import create_post_from_content


@pytest.mark.django_db
def test_create_post_from_content_builds_post(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace, external_id="P-1", angle="Solar story",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING,
        herald_content_id="ci-9",
        channel_targets=[{"platform": "linkedin", "account": "waiis"}],
    )
    content = {"id": "ci-9", "body": "Solar is booming across East Africa.", "title": "Solar"}
    post = create_post_from_content(content, intake)
    assert isinstance(post, Post)
    assert post.workspace_id == workspace.pk
    assert "Solar is booming" in post.caption
    intake.refresh_from_db()
    assert intake.post_id == post.pk


@pytest.mark.django_db
def test_create_post_no_matching_account_leaves_draft(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace, external_id="P-2", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING, herald_content_id="ci-10",
        channel_targets=[{"platform": "linkedin"}],
    )
    content = {"id": "ci-10", "body": "Body text", "title": "T"}
    post = create_post_from_content(content, intake)
    # No SocialAccount exists, so no PlatformPost — post stays draft-only
    assert post.platform_posts.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/approvals/tests/test_approve_creates_post.py -q`
Expected: FAIL — `ModuleNotFoundError: apps.approvals.intake_publish`

- [ ] **Step 3: Implement the post-creation helper**

```python
# apps/approvals/intake_publish.py
"""Create a publishable Django Post from an approved HERALD content item."""
from __future__ import annotations

import logging

from apps.composer.models import Post, PlatformPost
from apps.social_accounts.models import SocialAccount

logger = logging.getLogger(__name__)


def create_post_from_content(content: dict, intake) -> Post:
    """Build a Post (+ PlatformPosts for matching connected accounts) from a
    HERALD content item dict and its originating ContentIntake.

    If no SocialAccount matches a channel target, the Post is created without
    PlatformPosts (draft-only) so it is ready once the channel is connected.
    """
    body = str(content.get("body", "")).strip()
    title = str(content.get("title", "") or intake.angle)[:255]

    post = Post.objects.create(
        workspace=intake.workspace,
        title=title,
        caption=body,
    )

    # Match channel targets to connected SocialAccounts in this workspace.
    targets = intake.channel_targets or []
    wanted_platforms = {t.get("platform") for t in targets if t.get("platform")}
    for account in SocialAccount.objects.filter(
        workspace=intake.workspace, platform__in=wanted_platforms
    ):
        PlatformPost.objects.create(
            post=post,
            social_account=account,
            status=PlatformPost.Status.DRAFT,
        )

    intake.post = post
    intake.save(update_fields=["post", "updated_at"])
    return post
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/approvals/tests/test_approve_creates_post.py -q`
Expected: PASS (2 cases)

- [ ] **Step 5: Wire into the approve view**

In `apps/approvals/console_views.py`, replace `approval_decide` with:

```python
@login_required
@require_POST
def approval_decide(request, approval_id):
    decision = request.POST.get("decision", "")
    body = {"decision": decision}
    edit = request.POST.get("edit_text")
    if edit:
        body["edit_text"] = edit
    try:
        agent_post(f"/approvals/{approval_id}/decide", body)
    except Exception:
        pass

    if decision == "approve":
        _try_create_post(request, approval_id)

    return redirect("console:approvals")


def _try_create_post(request, approval_id):
    """On approve, pull the content item and create a publishable Post."""
    from apps.approvals.intake_publish import create_post_from_content
    from apps.content_intake.models import ContentIntake

    approval = safe_get(f"/approvals/{approval_id}", default=None)
    if not approval:
        return
    content_id = approval.get("target_id") or approval.get("content_id")
    if not content_id:
        return
    content = safe_get(f"/content/items/{content_id}", default=None)
    if not content:
        return
    intake = ContentIntake.objects.filter(
        workspace=getattr(request, "workspace", None),
        herald_content_id=str(content_id),
    ).first()
    if intake is None:
        return
    try:
        create_post_from_content(content, intake)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("post creation from approval failed")
```

- [ ] **Step 6: Run the approvals test module to confirm no regressions**

Run: `uv run pytest apps/approvals/tests/test_approve_creates_post.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/approvals/console_views.py apps/approvals/intake_publish.py apps/approvals/tests/test_approve_creates_post.py
git commit -m "feat(approvals): approve HERALD draft → auto-create publishable Post"
```

---

## Task 8: Wire the X/Twitter credential slot

**Files:**
- Modify: `config/settings/base.py`
- Modify: `.env.example`

- [ ] **Step 1: Check current state**

Run:
```bash
grep -n "twitter\|TWITTER" config/settings/base.py
```
Expected: shows `"twitter"` is NOT in `PLATFORM_CREDENTIALS_FROM_ENV` (only in the registry).

- [ ] **Step 2: Add the credential block**

In `config/settings/base.py`, near the other `_*_CREDENTIALS` blocks (before `PLATFORM_CREDENTIALS_FROM_ENV`), add:

```python
_TWITTER_CREDENTIALS = {
    "client_id": env("PLATFORM_TWITTER_CLIENT_ID", default=""),
    "client_secret": env("PLATFORM_TWITTER_CLIENT_SECRET", default=""),
}
```

Then add to the `PLATFORM_CREDENTIALS_FROM_ENV` dict:

```python
    "twitter": _TWITTER_CREDENTIALS,
```

- [ ] **Step 3: Add to .env.example**

In `.env.example`, after the LinkedIn block, add:

```
PLATFORM_TWITTER_CLIENT_ID=
PLATFORM_TWITTER_CLIENT_SECRET=
```

- [ ] **Step 4: Verify settings load**

Run:
```bash
uv run python manage.py shell -c "from django.conf import settings; print('twitter' in settings.PLATFORM_CREDENTIALS_FROM_ENV)"
```
Expected: `True`

- [ ] **Step 5: Commit**

```bash
git add config/settings/base.py .env.example
git commit -m "feat(providers): wire X/Twitter credential env slot"
```

---

## Task 9: Full suite + deploy verification

**Files:** none (verification).

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q --tb=short 2>&1 | tail -15`
Expected: all pass (≈ 800+).

- [ ] **Step 2: Push to GitHub**

```bash
git push origin main
```

- [ ] **Step 3: Deploy both services**

```bash
railway link --project 2ee08478-c28d-4e6e-a1d0-bf8d5c871051
railway up --service web
railway up --service worker
```

- [ ] **Step 4: Verify live routes (after deploy settles)**

```bash
curl -s -o /dev/null -w "intake:%{http_code}\n" https://web-production-2f84d.up.railway.app/console/intake/
curl -s -o /dev/null -w "news:%{http_code}\n" https://web-production-2f84d.up.railway.app/console/news
```
Expected: both `302` (redirect to login = route exists).

- [ ] **Step 5: Verify a live HERALD round-trip**

```bash
TOKEN="<AGENT_SERVICE_TOKEN>"
curl -s -X POST https://web-production-e7cf9.up.railway.app/agents/herald/draft \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"sector":"energy","brief":"Test: solar growth in East Africa","count":1}' | head -c 300
```
Expected: JSON with `variants`/`proposals` (a fresh draft).

- [ ] **Step 6: Commit verification note**

```bash
git commit --allow-empty -m "chore: bridge-two-brains deployed + verified live"
git push origin main
```

---

## Notes for the Operator

After deploy:
1. **Settings** → paste the Sheet ID, enable sync → wait 15 min (or trigger sync manually).
2. Watch the **Intake** board fill, then HERALD drafts auto-appear in **Drafts** / **AI Approvals**.
3. Approve a draft → a Post is created. To publish, connect the matching social account (LinkedIn first) with its OAuth app credentials in Railway.
