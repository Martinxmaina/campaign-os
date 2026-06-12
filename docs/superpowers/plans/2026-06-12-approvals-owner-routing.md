# Approvals + Owner Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route HERALD-drafted intake items to the right owner's AI Approvals queue (Django-side), where approve/changes/reject moves the post forward.

**Architecture:** A Django `owner_routing.resolve_reviewer(intake)` maps the sheet owner / pillar → a User (fallback: workspace owner/admin). Two new `Post` fields (`review_assignee`, `review_state`) hold the authoritative approval state — set when HERALD drafts. The console AI Approvals view reads Django Posts (`review_state="pending"`) and decides on them.

**Tech Stack:** Django 5.1, HTMX. uv at `/Users/macbook/.local/bin/uv`.

**Spec:** `docs/superpowers/specs/2026-06-12-approvals-owner-routing-design.md`

**Test command:** `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <path> -p no:warnings -q`

---

## File Map

**New:**
- `apps/content_intake/owner_routing.py` — `resolve_reviewer(intake)`
- `apps/content_intake/tests/test_owner_routing.py`
- `apps/composer/migrations/00XX_post_review_fields.py` (generated)
- `apps/approvals/tests/test_ai_approvals_queue.py`

**Modified:**
- `apps/composer/models.py` — `review_assignee` + `review_state` fields
- `apps/content_intake/draft_post.py` — assign reviewer + set pending on draft
- `apps/approvals/console_views.py` — Django-backed `ai_approvals` + `approval_decide`
- `templates/console/approvals.html` — queue UI

---

## Task 1: Owner resolution helper

**Files:**
- Create: `apps/content_intake/owner_routing.py`
- Test: `apps/content_intake/tests/test_owner_routing.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_owner_routing.py
import pytest
from apps.content_intake.owner_routing import resolve_reviewer
from apps.content_intake.models import ContentIntake


def _user(email, name, workspace, role="member"):
    from django.contrib.auth import get_user_model
    from apps.members.models import WorkspaceMembership
    u = get_user_model().objects.create_user(email=email, password="pw12345678", name=name)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role=role)
    return u


@pytest.mark.django_db
def test_matches_owner_raw_by_name(workspace):
    carren = _user("carren@afcen.org", "Carren Atieno", workspace)
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-1",
        pillar_theme="Agribusiness", owner_raw="Carren", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(item) == carren


@pytest.mark.django_db
def test_falls_back_to_pillar_owner(workspace):
    dennis = _user("dennis@afcen.org", "Dennis Mwangi", workspace)
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-2",
        pillar_theme="Energy", owner_raw="", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(item) == dennis


@pytest.mark.django_db
def test_falls_back_to_workspace_owner_when_unmapped(workspace):
    boss = _user("boss@afcen.org", "Boss Lady", workspace, role="owner")
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-3",
        pillar_theme="Totally Unknown Pillar", owner_raw="Nobody", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(item) == boss


@pytest.mark.django_db
def test_returns_none_when_no_owner_exists(workspace):
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-4",
        pillar_theme="X", owner_raw="Y", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(item) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_owner_routing.py -p no:warnings -q`
Expected: FAIL — `ModuleNotFoundError: apps.content_intake.owner_routing`

- [ ] **Step 3: Implement `owner_routing.py`**

```python
# apps/content_intake/owner_routing.py
"""Resolve the User who should review a HERALD-drafted intake item.

Priority: the sheet's named owner → the pillar's default owner → the workspace
owner/admin (fallback). All lookups are scoped to the intake's workspace members.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.content_intake.sector_map import map_pillar_to_sector

# Canonical owner per pillar/sector (sector_map normalizes pillar_theme → sector).
OWNER_BY_PILLAR = {
    "energy": "Dennis",
    "agribusiness": "Carren",
    "ai": "Joseph",
    "digital": "Nduta",
    "minerals": "Dennis",
}


def _find_member(workspace, name_or_email: str):
    """Return a workspace member matching a name/email fragment, or None."""
    q = (name_or_email or "").strip()
    if not q:
        return None
    User = get_user_model()
    return (
        User.objects.filter(workspace_memberships__workspace=workspace)
        .filter(Q(name__icontains=q) | Q(email__istartswith=q.lower()))
        .distinct()
        .first()
    )


def _workspace_owner(workspace):
    """Return a workspace owner/admin User, or None."""
    from apps.members.models import WorkspaceMembership
    m = (
        WorkspaceMembership.objects.filter(
            workspace=workspace, workspace_role__in=("owner", "admin")
        )
        .select_related("user")
        .order_by("workspace_role")  # 'admin' < 'owner' alphabetically; either is fine
        .first()
    )
    return m.user if m else None


def resolve_reviewer(intake):
    """Return the User to assign this intake's approval to (or None)."""
    ws = intake.workspace
    # 1) The sheet's explicit owner.
    user = _find_member(ws, intake.owner_raw)
    if user:
        return user
    # 2) The pillar's default owner.
    sector = map_pillar_to_sector(intake.pillar_theme)
    owner_name = OWNER_BY_PILLAR.get(sector)
    # Also try a direct lowercase match on the raw pillar (e.g. "digital").
    if not owner_name:
        owner_name = OWNER_BY_PILLAR.get((intake.pillar_theme or "").strip().lower())
    if owner_name:
        user = _find_member(ws, owner_name)
        if user:
            return user
    # 3) Fallback: workspace owner/admin.
    return _workspace_owner(ws)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_owner_routing.py -p no:warnings -q`
Expected: PASS (4 cases)

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/owner_routing.py apps/content_intake/tests/test_owner_routing.py
git commit -m "feat(intake): owner_routing.resolve_reviewer — sheet owner → pillar owner → workspace owner"
```

---

## Task 2: `Post.review_assignee` + `review_state` fields

**Files:**
- Modify: `apps/composer/models.py`
- Create: `apps/composer/migrations/00XX_post_review_fields.py`
- Test: `apps/content_intake/tests/test_owner_routing.py` (add a field-default case)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_owner_routing.py`:

```python
@pytest.mark.django_db
def test_post_review_fields_default(workspace):
    from apps.composer.models import Post
    p = Post.objects.create(workspace=workspace, title="t", caption="c")
    assert p.review_assignee is None
    assert p.review_state == "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_owner_routing.py::test_post_review_fields_default -p no:warnings -q`
Expected: FAIL — `AttributeError: ... 'review_assignee'`

- [ ] **Step 3: Add the fields**

In `apps/composer/models.py`, in the `Post` class (near `scheduled_at`/other fields), add:

```python
    class ReviewState(models.TextChoices):
        NONE = "none", "None"
        PENDING = "pending", "Pending Review"
        APPROVED = "approved", "Approved"
        CHANGES_REQUESTED = "changes_requested", "Changes Requested"
        REJECTED = "rejected", "Rejected"

    review_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="review_queue",
        help_text="User responsible for approving this AI-drafted post.",
    )
    review_state = models.CharField(
        max_length=20, choices=ReviewState.choices, default=ReviewState.NONE, db_index=True,
        help_text="Authoritative AI-approval state, independent of per-platform status.",
    )
```

(`settings` is already imported in this module — it uses `settings.AUTH_USER_MODEL` for `author`.)

- [ ] **Step 4: Generate + run migration**

Run:
```bash
DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run python manage.py makemigrations composer --name post_review_fields
DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run python manage.py migrate
```
Expected: migration created + applied.

- [ ] **Step 5: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_owner_routing.py::test_post_review_fields_default -p no:warnings -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/composer/models.py apps/composer/migrations/ apps/content_intake/tests/test_owner_routing.py
git commit -m "feat(composer): Post.review_assignee + review_state for AI-approval routing"
```

---

## Task 3: Assign reviewer + set pending on draft

**Files:**
- Modify: `apps/content_intake/draft_post.py`
- Test: `apps/content_intake/tests/test_draft_post.py` (add cases)

- [ ] **Step 1: Write the failing test**

Append to `apps/content_intake/tests/test_draft_post.py`:

```python
@pytest.mark.django_db
def test_ensure_draft_post_assigns_reviewer_and_pending(workspace):
    from unittest.mock import patch
    from django.contrib.auth import get_user_model
    from apps.members.models import WorkspaceMembership
    from apps.content_intake.models import ContentIntake
    from apps.content_intake.draft_post import ensure_draft_post
    dennis = get_user_model().objects.create_user(email="dennis@afcen.org", password="pw12345678", name="Dennis")
    WorkspaceMembership.objects.create(user=dennis, workspace=workspace, workspace_role="member")
    item = ContentIntake.objects.create(workspace=workspace, external_id="DR-1",
        pillar_theme="Energy", angle="Solar", sensitivity="public_safe", status="drafting")
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        post = ensure_draft_post(item)
    assert post.review_assignee == dennis
    assert post.review_state == "pending"


@pytest.mark.django_db
def test_ensure_draft_post_does_not_downgrade_approved(workspace):
    from unittest.mock import patch
    from apps.content_intake.models import ContentIntake
    from apps.content_intake.draft_post import ensure_draft_post
    from apps.composer.models import Post
    post = Post.objects.create(workspace=workspace, title="t", caption="c", review_state="approved")
    item = ContentIntake.objects.create(workspace=workspace, external_id="DR-2", angle="x",
        sensitivity="public_safe", status="drafting", post=post)
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        out = ensure_draft_post(item)
    assert out.pk == post.pk
    out.refresh_from_db()
    assert out.review_state == "approved"  # not downgraded
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_draft_post.py -p no:warnings -q -k "reviewer or downgrade"`
Expected: FAIL — review fields not set by `ensure_draft_post`.

- [ ] **Step 3: Wire assignment into `ensure_draft_post`**

In `apps/content_intake/draft_post.py`, add an import:

```python
from apps.content_intake.owner_routing import resolve_reviewer
```

Add a helper and call it on both return paths (existing-post and freshly-created):

```python
def _assign_review(post, intake):
    """Route the post to its owner + mark pending, without downgrading an
    already-decided post. Idempotent."""
    changed = []
    if post.review_assignee_id is None:
        post.review_assignee = resolve_reviewer(intake)
        changed.append("review_assignee")
    if post.review_state in ("none", "changes_requested"):
        post.review_state = post.ReviewState.PENDING
        changed.append("review_state")
    if changed:
        post.save(update_fields=[*changed, "updated_at"])
    return post
```

Then in `ensure_draft_post`, wrap each return:
- the `if intake.post_id: return intake.post` line → `if intake.post_id: return _assign_review(intake.post, intake)`
- the `if content: return create_post_from_content(content, intake)` line →
  `if content: return _assign_review(create_post_from_content(content, intake), intake)`
- the final minimal-Post path → `return _assign_review(post, intake)`

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_draft_post.py -p no:warnings -q`
Expected: PASS (existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add apps/content_intake/draft_post.py apps/content_intake/tests/test_draft_post.py
git commit -m "feat(intake): assign reviewer + set review_state=pending when HERALD drafts"
```

---

## Task 4: Django AI Approvals queue + decide

**Files:**
- Modify: `apps/approvals/console_views.py`
- Modify: `templates/console/approvals.html`
- Test: `apps/approvals/tests/test_ai_approvals_queue.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/approvals/tests/test_ai_approvals_queue.py
import pytest
from django.urls import reverse
from apps.composer.models import Post


@pytest.fixture
def reviewer(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    return org_owner


@pytest.mark.django_db
def test_queue_shows_my_pending_posts(client, reviewer, workspace):
    mine = Post.objects.create(workspace=workspace, title="Mine", caption="c",
        review_assignee=reviewer, review_state="pending")
    Post.objects.create(workspace=workspace, title="Draftish", caption="c", review_state="none")
    resp = client.get(reverse("console:approvals"))
    assert resp.status_code == 200
    assert b"Mine" in resp.content
    assert b"Draftish" not in resp.content


@pytest.mark.django_db
def test_approve_sets_state_and_records_action(client, reviewer, workspace):
    from apps.approvals.models import ApprovalAction
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_assignee=reviewer, review_state="pending")
    url = reverse("console:approval-decide", args=[post.id])
    resp = client.post(url, {"decision": "approve"})
    assert resp.status_code in (200, 302)
    post.refresh_from_db()
    assert post.review_state == "approved"
    assert ApprovalAction.objects.filter(post=post, action="approved").exists()


@pytest.mark.django_db
def test_reject_and_changes(client, reviewer, workspace):
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_assignee=reviewer, review_state="pending")
    url = reverse("console:approval-decide", args=[post.id])
    client.post(url, {"decision": "reject"})
    post.refresh_from_db()
    assert post.review_state == "rejected"
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/approvals/tests/test_ai_approvals_queue.py -p no:warnings -q`
Expected: FAIL — view still agent-service-backed; `approval-decide` expects a UUID post id and Django logic.

- [ ] **Step 3: Rewrite `console_views.py` for Django Posts**

Replace `apps/approvals/console_views.py` with:

```python
"""AI Approvals — Django-backed queue for HERALD-drafted Posts, routed by owner."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.approvals.models import ApprovalAction
from apps.composer.models import Post


def _is_ws_admin(request):
    ws = getattr(request, "workspace", None)
    m = request.user.workspace_memberships.filter(workspace=ws).first() if ws else None
    return bool(m and m.workspace_role in ("owner", "admin"))


@login_required
def ai_approvals(request):
    ws = getattr(request, "workspace", None)
    qs = Post.objects.none()
    if ws is not None:
        qs = Post.objects.filter(workspace=ws, review_state=Post.ReviewState.PENDING)
        if not _is_ws_admin(request):
            qs = qs.filter(review_assignee=request.user)
        qs = qs.select_related("review_assignee").order_by("-updated_at")
    return render(request, "console/approvals.html", {"items": list(qs[:200]), "down": False})


@login_required
@require_POST
def approval_decide(request, approval_id):
    """approval_id is a Post UUID (the queue lists Posts)."""
    ws = getattr(request, "workspace", None)
    post = get_object_or_404(Post, id=approval_id, workspace=ws)
    decision = request.POST.get("decision", "")

    if decision == "approve":
        post.review_state = Post.ReviewState.APPROVED
        ApprovalAction.objects.create(post=post, user=request.user, action=ApprovalAction.ActionType.APPROVED)
        # Move any pending_review children toward approved so the publish path can run.
        post.platform_posts.filter(status="pending_review").update(status="approved")
    elif decision == "changes":
        post.review_state = Post.ReviewState.CHANGES_REQUESTED
        ApprovalAction.objects.create(post=post, user=request.user, action=ApprovalAction.ActionType.CHANGES_REQUESTED,
                                      comment=request.POST.get("comment", ""))
    elif decision == "reject":
        post.review_state = Post.ReviewState.REJECTED
        ApprovalAction.objects.create(post=post, user=request.user, action=ApprovalAction.ActionType.REJECTED)
    post.save(update_fields=["review_state", "updated_at"])
    return redirect("console:approvals")
```

- [ ] **Step 4: Update the template**

Replace `templates/console/approvals.html`'s item rendering to use Django Posts. Keep it extending the console base. Body:

```html
{% extends "console/base.html" %}
{% block content %}
<div class="p-6">
  <h1 class="text-2xl font-bold mb-4">AI Approvals</h1>
  <div class="space-y-3">
    {% for post in items %}
    <div class="rounded-lg border border-stone-200 bg-white p-4">
      <div class="flex items-start justify-between">
        <div>
          <h3 class="font-semibold">{{ post.title|default:"Untitled" }}</h3>
          <p class="text-sm text-stone-600">{{ post.caption|truncatechars:160 }}</p>
          <p class="text-xs text-stone-400 mt-1">Assigned: {{ post.review_assignee.name|default:post.review_assignee.email|default:"—" }}</p>
        </div>
        <div class="flex gap-2">
          <form method="post" action="{% url 'console:approval-decide' post.id %}">{% csrf_token %}
            <input type="hidden" name="decision" value="approve">
            <button class="rounded bg-green-600 text-white px-3 py-1 text-xs">Approve</button></form>
          <form method="post" action="{% url 'console:approval-decide' post.id %}">{% csrf_token %}
            <input type="hidden" name="decision" value="changes">
            <button class="rounded bg-amber-500 text-white px-3 py-1 text-xs">Request changes</button></form>
          <form method="post" action="{% url 'console:approval-decide' post.id %}">{% csrf_token %}
            <input type="hidden" name="decision" value="reject">
            <button class="rounded bg-red-500 text-white px-3 py-1 text-xs">Reject</button></form>
        </div>
      </div>
    </div>
    {% empty %}
    <p class="text-stone-400">No posts awaiting your approval.</p>
    {% endfor %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/approvals/tests/test_ai_approvals_queue.py -p no:warnings -q`
Expected: PASS (3 cases). Also run `apps/approvals/` to catch regressions from the console_views rewrite:
`DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/approvals/ -p no:warnings -q`

- [ ] **Step 6: Commit**

```bash
git add apps/approvals/console_views.py templates/console/approvals.html apps/approvals/tests/test_ai_approvals_queue.py
git commit -m "feat(approvals): Django AI Approvals queue routed by review_assignee + approve/changes/reject"
```

---

## Task 5: Full suite + deploy verification

**Files:** none (verification).

- [ ] **Step 1: Full suite**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest -p no:warnings -q 2>&1 | tail -10`
Expected: all pass. If the old agent-service-backed approvals test (`apps/intelligence/tests/test_console_news.py` or a console approvals test) asserts the old behavior, update it to the Django queue.

- [ ] **Step 2: Push + deploy**

```bash
git push origin main
railway link --project 2ee08478-c28d-4e6e-a1d0-bf8d5c871051
railway up --service web
railway up --service worker
```

- [ ] **Step 3: Verify live + migration applied**

```bash
until [ "$(curl -s -o /dev/null -w '%{http_code}' https://web-production-2f84d.up.railway.app/console/approvals)" != "000" ]; do sleep 8; done
curl -s -o /dev/null -w "approvals:%{http_code}\n" https://web-production-2f84d.up.railway.app/console/approvals
```
Expected: `302` (redirect to login = route exists; migration ran on deploy).

- [ ] **Step 4: Verification commit**

```bash
git commit --allow-empty -m "chore: approvals + owner routing deployed + verified"
git push origin main
```

---

## Notes for the Operator

- When you Draft-with-HERALD an intake item, it's auto-routed to its owner
  (sheet owner → pillar owner → workspace owner) and appears in **AI Approvals** for that person.
- Owners see their queue; workspace owners/admins see all pending.
- Approve → the post is cleared (and any connected channels move to approved, ready to schedule/publish).
- Pillar→owner: Energy→Dennis · Agribusiness→Carren · AI→Joseph · Digital→Nduta · Minerals→Dennis.
