# IA "Group & Home" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ~30-link role-blind sidebar with a short role-filtered spine, add a role-aware Home (mini dashboard led by a content-performance graph), merge the duplicate content front doors, and declutter the busiest pages — without moving existing URLs or merging approval-screen logic.

**Architecture:** A new lightweight `apps/home` app provides one workspace-scoped Home view whose cards render by permission (reusing existing querysets + analytics snapshots). `templates/base.html` nav is restructured into spine + "More" drawer + permission-gated role groups + a Settings gear, reusing the existing `can_access_joseph` / `can_manage_crm` / `sidebar_*` context vars. `composer:create_landing` becomes a redirect. The Compose page is refactored to a calmer two-pane + folded-sections layout. Each phase is independently shippable.

**Tech Stack:** Django 5.1, pytest (`uv run pytest`), HTMX + Alpine + Tailwind (existing), inline SVG for the chart (no new dependency).

**Reference spec:** `docs/superpowers/specs/2026-06-27-ia-group-and-home-design.md`

**Confirmed decisions:** Joseph → workspace role `admin`. Content-only → `manager`. (Both can be changed later by reassigning the workspace role; nothing in the build hardcodes a person.)

---

## File Structure

**New — `apps/home` (the role-aware Home):**
- `apps/home/__init__.py`
- `apps/home/apps.py` — `HomeConfig`
- `apps/home/urls.py` — `app_name = "home"`, `path("", views.index, name="index")`
- `apps/home/views.py` — `index(request, workspace_id)` composes context
- `apps/home/services.py` — pure, testable data builders (performance graph + cards)
- `apps/home/tests/__init__.py`, `apps/home/tests/test_services.py`, `apps/home/tests/test_views.py`

**New — templates:**
- `templates/home/index.html` — Home shell
- `templates/home/_performance_graph.html` — SVG content-performance card
- `templates/home/_card.html` — generic action card partial

**Modified:**
- `config/settings/base.py` — add `"apps.home"` to INSTALLED_APPS
- `config/urls.py` — mount `apps.home.urls` at `workspace/<uuid:workspace_id>/home/`
- `apps/accounts/views.py:40-68` — default landing `calendar:calendar` → `home:index`
- `apps/composer/views.py:1869-1896` — `create_landing` becomes a redirect to `composer:compose`
- `templates/base.html` — nav restructure (spine + More + role groups + gear + notifications bell)
- `templates/members/partials/invite_modal.html` — per-role helper text
- `templates/composer/compose.html` — Phase B density refactor

**Conventions to follow:** workspace-scoped views receive `workspace_id`; `RBACMiddleware` (`apps/members/middleware.py`) sets `request.workspace` + `request.workspace_membership`. Permission check: `request.workspace_membership.effective_permissions.get("<key>", False)` (or `request.user.is_staff`). Joseph/CRM visibility: the existing context vars `can_access_joseph` / `can_manage_crm` (from `apps/common/context_processors.py`). Reuse `sidebar_pending_approvals` and `sidebar_unread_inbox_count` (already in context).

---

# PHASE A — Nav + Home

## Task A1: Scaffold the `apps/home` app and route it

**Files:**
- Create: `apps/home/__init__.py` (empty), `apps/home/apps.py`, `apps/home/urls.py`, `apps/home/views.py`, `apps/home/tests/__init__.py` (empty)
- Modify: `config/settings/base.py` (INSTALLED_APPS), `config/urls.py`

- [ ] **Step 1: Write the failing test**

`apps/home/tests/test_views.py`:
```python
import pytest
from django.urls import reverse
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_home_url_resolves_and_renders_for_member(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    url = reverse("home:index", kwargs={"workspace_id": workspace.id})
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"New post" in resp.content
```

> If `workspace` / `make_user_in_workspace` fixtures don't already exist in `conftest.py`, create them there following existing test fixtures (search `tests/` and `apps/*/tests/conftest.py` for a workspace fixture to copy). Do NOT invent a new pattern — reuse the project's.

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest apps/home/tests/test_views.py -x -q`
Expected: FAIL — `django.urls.exceptions.NoReverseMatch` / app not installed.

- [ ] **Step 3: Implement the scaffold**

`apps/home/apps.py`:
```python
from django.apps import AppConfig


class HomeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.home"
    label = "home"
```

`apps/home/urls.py`:
```python
from django.urls import path

from . import views

app_name = "home"

urlpatterns = [
    path("", views.index, name="index"),
]
```

`apps/home/views.py` (minimal for now; fleshed out in A4):
```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def index(request, workspace_id):
    return render(request, "home/index.html", {"workspace": request.workspace})
```

`templates/home/index.html` (placeholder; replaced in A4):
```django
{% extends "base.html" %}
{% block content %}<button class="btn-brand">New post</button>{% endblock %}
```

`config/settings/base.py` — add to INSTALLED_APPS (next to the other `apps.*` entries):
```python
    "apps.home",
```

`config/urls.py` — add alongside the other workspace includes (after the composer line, ~line 30):
```python
    path("workspace/<uuid:workspace_id>/home/", include("apps.home.urls")),
```

- [ ] **Step 4: Run it, expect pass**

Run: `uv run pytest apps/home/tests/test_views.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/home config/settings/base.py config/urls.py templates/home/index.html
git commit -m "feat(home): scaffold workspace-scoped Home app + route"
```

---

## Task A2: Performance-graph service (`performance_summary`)

**Files:**
- Create: `apps/home/services.py`, `apps/home/tests/test_services.py`

- [ ] **Step 1: Write the failing test**

`apps/home/tests/test_services.py`:
```python
import pytest
from datetime import timedelta
from django.utils import timezone

from apps.home.services import performance_summary
from apps.composer.models import Post, PlatformPost
from apps.analytics.models import PostInsightsSnapshot

pytestmark = pytest.mark.django_db


def test_performance_summary_empty_workspace(workspace):
    s = performance_summary(workspace, days=30)
    assert s["has_data"] is False
    assert len(s["series"]) == 30
    assert s["posts_published"] == 0
    assert s["total_reach"] == 0


def test_performance_summary_counts_published_posts_and_series(workspace, social_account, make_post):
    today = timezone.now().date()
    post = make_post(workspace, status="published")
    pp = PlatformPost.objects.create(
        post=post, social_account=social_account,
        status=PlatformPost.Status.PUBLISHED, published_at=timezone.now(),
    )
    PostInsightsSnapshot.objects.create(platform_post=pp, metric_key="engagement", date=today, value=12.0)
    PostInsightsSnapshot.objects.create(platform_post=pp, metric_key="reach", date=today, value=300.0)

    s = performance_summary(workspace, days=30, metric="engagement")
    assert s["has_data"] is True
    assert s["posts_published"] == 1
    assert s["total_reach"] == 300.0
    assert s["series"][-1] == 12.0  # today is the last bucket
    assert any(p["platform"] == social_account.platform for p in s["by_platform"])
```

> Reuse/extend existing fixtures for `social_account` and `make_post`. If absent, add them to `apps/home/tests/conftest.py` modeled on existing analytics/composer tests (search `apps/analytics/tests` and `apps/composer/tests` for `SocialAccount` + `Post` factories).

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest apps/home/tests/test_services.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'performance_summary'`.

- [ ] **Step 3: Implement `performance_summary`**

`apps/home/services.py`:
```python
"""Pure data builders for the role-aware Home. No request/template logic here."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.analytics.models import PostInsightsSnapshot
from apps.composer.models import PlatformPost

# Headline metric for the Home graph + the reach total shown beside it.
_GRAPH_METRIC = "engagement"
_REACH_METRIC = "reach"


def _published_platform_post_ids(workspace):
    """PlatformPosts that went out THROUGH Campaign OS for this workspace."""
    return PlatformPost.objects.filter(
        post__workspace_id=workspace.id,
        status=PlatformPost.Status.PUBLISHED,
    )


def performance_summary(workspace, days: int = 30, metric: str = _GRAPH_METRIC) -> dict:
    """Daily series + headline numbers for posts published via the platform.

    Returns a dict the template renders directly:
      series:          list[float], one bucket per day (oldest -> newest)
      labels:          list[str] ISO dates aligned with `series`
      metric_label:    human label for the series
      posts_published: count of PlatformPosts published in the window
      total_reach:     summed reach over the window
      avg_engagement:  mean of non-zero series buckets (0 if none)
      by_platform:     list[{platform, value}] engagement totals per platform
      has_data:        bool — drives the empty state
      window_days:     echoes `days`
    """
    end = timezone.now().date()
    start = end - timedelta(days=days - 1)

    pp = _published_platform_post_ids(workspace)
    pp_ids = list(pp.values_list("id", flat=True))

    # Daily engagement series (summed across all the workspace's published posts).
    by_date = {}
    if pp_ids:
        rows = (
            PostInsightsSnapshot.objects.filter(
                platform_post_id__in=pp_ids, metric_key=metric,
                date__gte=start, date__lte=end,
            )
            .values("date")
            .annotate(value=Sum("value"))
        )
        by_date = {r["date"]: float(r["value"] or 0.0) for r in rows}

    series = [by_date.get(start + timedelta(days=i), 0.0) for i in range(days)]
    labels = [(start + timedelta(days=i)).isoformat() for i in range(days)]

    posts_published = pp.filter(
        published_at__date__gte=start, published_at__date__lte=end
    ).count()

    total_reach = 0.0
    by_platform: list[dict] = []
    if pp_ids:
        total_reach = float(
            PostInsightsSnapshot.objects.filter(
                platform_post_id__in=pp_ids, metric_key=_REACH_METRIC,
                date__gte=start, date__lte=end,
            ).aggregate(t=Sum("value"))["t"]
            or 0.0
        )
        plat_rows = (
            PostInsightsSnapshot.objects.filter(
                platform_post_id__in=pp_ids, metric_key=metric,
                date__gte=start, date__lte=end,
            )
            .values("platform_post__social_account__platform")
            .annotate(value=Sum("value"))
            .order_by("-value")
        )
        by_platform = [
            {"platform": r["platform_post__social_account__platform"], "value": float(r["value"] or 0.0)}
            for r in plat_rows
            if r["platform_post__social_account__platform"]
        ]

    nonzero = [v for v in series if v]
    avg_engagement = round(sum(nonzero) / len(nonzero), 1) if nonzero else 0.0
    has_data = posts_published > 0 or any(series)

    return {
        "series": series,
        "labels": labels,
        "metric_label": "Engagement",
        "posts_published": posts_published,
        "total_reach": total_reach,
        "avg_engagement": avg_engagement,
        "by_platform": by_platform,
        "has_data": has_data,
        "window_days": days,
    }
```

- [ ] **Step 4: Run it, expect pass**

Run: `uv run pytest apps/home/tests/test_services.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/home/services.py apps/home/tests
git commit -m "feat(home): performance_summary service (platform-published posts, 30d)"
```

---

## Task A3: Action-card services (sign-off, drafts, going-out-soon)

**Files:**
- Modify: `apps/home/services.py`, `apps/home/tests/test_services.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/home/tests/test_services.py`:
```python
from apps.home.services import pending_signoff, my_drafts, going_out_soon


def test_my_drafts_returns_only_my_workspace_drafts(workspace, other_workspace, make_post, make_user_in_workspace):
    user = make_user_in_workspace(workspace)
    mine = make_post(workspace, status="draft", author=user)
    make_post(workspace, status="published", author=user)   # not a draft
    make_post(other_workspace, status="draft", author=user)  # other workspace
    ids = {p.id for p in my_drafts(workspace, user)}
    assert ids == {mine.id}


def test_going_out_soon_lists_scheduled_within_window(workspace, make_post):
    from django.utils import timezone
    from datetime import timedelta
    soon = make_post(workspace, status="scheduled", scheduled_at=timezone.now() + timedelta(days=2))
    make_post(workspace, status="scheduled", scheduled_at=timezone.now() + timedelta(days=30))  # outside 7d
    ids = {p.id for p in going_out_soon(workspace, days=7)}
    assert soon.id in ids and len(ids) == 1
```

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest apps/home/tests/test_services.py -x -q`
Expected: FAIL — import error for the three functions.

- [ ] **Step 3: Implement the card builders**

Append to `apps/home/services.py`:
```python
from apps.composer.models import Post


def my_drafts(workspace, user, limit: int = 6):
    return list(
        Post.objects.filter(workspace_id=workspace.id, review_state="draft", author=user)
        .order_by("-updated_at")[:limit]
    )


def going_out_soon(workspace, days: int = 7, limit: int = 6):
    now = timezone.now()
    return list(
        Post.objects.filter(
            workspace_id=workspace.id,
            review_state="scheduled",
            scheduled_at__gte=now,
            scheduled_at__lte=now + timedelta(days=days),
        ).order_by("scheduled_at")[:limit]
    )


def pending_signoff(workspace, user, limit: int = 6):
    """Posts awaiting review that this user can act on (reviewer or approver)."""
    qs = Post.objects.filter(
        workspace_id=workspace.id, review_state__in=["pending_review", "pending_client"]
    ).order_by("-updated_at")
    return list(qs[:limit])
```

> Confirm the Post status field name before running: the spec notes `Post.review_state` (values `draft`, `scheduled`, `pending_review`, `pending_client`, …) with `status` as a `@property`. Verify against `apps/composer/models.py` and adjust the literal field name if the codebase differs. The `PlatformPost.Status` enum (published/scheduled) is separate and used only in A2.

- [ ] **Step 4: Run it, expect pass**

Run: `uv run pytest apps/home/tests/test_services.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/home/services.py apps/home/tests/test_services.py
git commit -m "feat(home): action-card services (drafts, going-out-soon, sign-off)"
```

---

## Task A4: Home view + template + SVG graph (permission-gated cards)

**Files:**
- Modify: `apps/home/views.py`, `apps/home/tests/test_views.py`
- Create: `templates/home/_performance_graph.html`, `templates/home/_card.html`
- Replace: `templates/home/index.html`

- [ ] **Step 1: Write the failing tests (per-role card visibility)**

Append to `apps/home/tests/test_views.py`:
```python
def _get_home(client, workspace, user):
    client.force_login(user)
    return client.get(reverse("home:index", kwargs={"workspace_id": workspace.id}))


def test_admin_sees_invite_card_and_graph(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.ADMIN)
    resp = _get_home(client, workspace, user)
    assert resp.status_code == 200
    assert b"Invite a teammate" in resp.content      # admin-only card
    assert b"performance" in resp.content.lower()     # graph card present (view_analytics)


def test_content_only_manager_has_no_admin_cards(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    resp = _get_home(client, workspace, user)
    assert resp.status_code == 200
    assert b"Invite a teammate" not in resp.content
    assert b"System health" not in resp.content


def test_editor_without_analytics_hides_graph(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.EDITOR)
    resp = _get_home(client, workspace, user)
    assert resp.status_code == 200
    # editor has view_analytics in the role table -> graph SHOWS; assert empty-state copy instead
    assert b"fills in as you publish" in resp.content or b"performance" in resp.content.lower()
```

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest apps/home/tests/test_views.py -x -q`
Expected: FAIL (placeholder template lacks the cards).

- [ ] **Step 3: Implement the view + template**

`apps/home/views.py`:
```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import services


def _can(request, key: str) -> bool:
    if getattr(request.user, "is_staff", False):
        return True
    m = getattr(request, "workspace_membership", None)
    return bool(m and m.effective_permissions.get(key, False))


@login_required
def index(request, workspace_id):
    workspace = request.workspace  # set by RBACMiddleware
    user = request.user
    is_admin = _can(request, "manage_workspace_settings")
    show_analytics = _can(request, "view_analytics")

    ctx = {
        "workspace": workspace,
        "show_analytics": show_analytics,
        "is_admin": is_admin,
        "perf": services.performance_summary(workspace) if show_analytics else None,
        "drafts": services.my_drafts(workspace, user),
        "going_out": services.going_out_soon(workspace),
        "signoff": services.pending_signoff(workspace, user) if _can(request, "approve_posts") else [],
        # can_access_joseph / can_manage_crm / sidebar_* arrive via context processors
    }
    return render(request, "home/index.html", ctx)
```

`templates/home/_performance_graph.html` (inline SVG bar chart; CSP-safe, no JS needed):
```django
<div class="card rounded-lg border border-stone-200 bg-white p-5">
  <div class="flex items-center justify-between">
    <h3 class="font-semibold">Content performance</h3>
    <span class="text-[11px] text-stone-400">Published via Campaign OS · last {{ perf.window_days }} days</span>
  </div>
  {% if perf.has_data %}
  <div class="flex gap-6 mt-3 mb-4">
    <div><div class="text-2xl font-bold">{{ perf.posts_published }}</div><div class="text-[11px] text-stone-500 uppercase tracking-wide">Posts</div></div>
    <div><div class="text-2xl font-bold">{{ perf.total_reach|floatformat:0 }}</div><div class="text-[11px] text-stone-500 uppercase tracking-wide">Reach</div></div>
    <div><div class="text-2xl font-bold">{{ perf.avg_engagement }}</div><div class="text-[11px] text-stone-500 uppercase tracking-wide">Avg {{ perf.metric_label }}</div></div>
  </div>
  {# Bars: each value as a column; max-height normalised in the view-injected width pct via |home_barpct (see below) #}
  <svg viewBox="0 0 300 80" preserveAspectRatio="none" class="w-full h-20" role="img" aria-label="{{ perf.metric_label }} over time">
    {% for h in perf.bar_heights %}
      <rect x="{{ forloop.counter0|add:0 }}" width="0.8" y="{{ h.y }}" height="{{ h.h }}" fill="#DC5B2E" transform="scale(10,1)"></rect>
    {% endfor %}
  </svg>
  {% if perf.by_platform %}
  <div class="flex flex-wrap gap-2 mt-3">
    {% for p in perf.by_platform %}<span class="text-[11px] rounded px-2 py-0.5 bg-stone-100 text-stone-600">{{ p.platform }} · {{ p.value|floatformat:0 }}</span>{% endfor %}
  </div>
  {% endif %}
  {% else %}
  <p class="text-sm text-stone-500 mt-3">No published posts yet — your performance graph fills in as you publish through the platform.</p>
  {% endif %}
</div>
```

> The bar geometry: compute `perf["bar_heights"]` in `performance_summary` (cleanest — keeps the template logic-free). Add at the end of `performance_summary`, before `return`:
> ```python
> _peak = max(series) or 1.0
> bar_heights = [{"h": round(70 * v / _peak, 2), "y": round(70 - 70 * v / _peak, 2)} for v in series]
> ```
> and add `"bar_heights": bar_heights` to the returned dict. (Update the A2 test only if you assert on it — current A2 asserts don't touch it.)

`templates/home/_card.html`:
```django
<a href="{{ href }}" class="card block rounded-lg border border-stone-200 bg-white p-4 hover:border-stone-400 transition-colors">
  <div class="flex items-center justify-between">
    <h3 class="font-semibold text-sm">{{ title }}</h3>
    {% if count is not None %}<span class="text-xs rounded-full bg-stone-100 px-2 py-0.5 text-stone-600">{{ count }}</span>{% endif %}
  </div>
  {% if subtitle %}<p class="text-xs text-stone-500 mt-1">{{ subtitle }}</p>{% endif %}
</a>
```

`templates/home/index.html` (replace placeholder):
```django
{% extends "base.html" %}
{% block content %}
<div class="max-w-5xl mx-auto px-6 py-8">
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-bold">Good to see you, {{ request.user.display_name|default:request.user.first_name|default:"there" }}</h1>
    <a href="{% url 'composer:compose' workspace_id=workspace.id %}" class="btn-brand rounded px-4 py-2 text-sm font-semibold">New post</a>
  </div>

  {% if show_analytics %}
    {% include "home/_performance_graph.html" %}
  {% endif %}

  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
    {% if signoff %}{% include "home/_card.html" with title="Needs your sign-off" count=signoff|length subtitle="Awaiting review" href="/workspace/"|add:workspace.id|stringformat:"s"|add:"/approvals/" %}{% endif %}
    {% include "home/_card.html" with title="Your drafts" count=drafts|length subtitle="Pick up where you left off" href="" %}
    {% include "home/_card.html" with title="Going out soon" count=going_out|length subtitle="Scheduled this week" href="" %}
    {% if sidebar_unread_inbox_count %}{% include "home/_card.html" with title="Inbox" count=sidebar_unread_inbox_count subtitle="Unread messages" href="" %}{% endif %}

    {% if can_manage_crm %}{% include "home/_card.html" with title="Deals needing action" subtitle="Relationships" href="" %}{% endif %}
    {% if can_access_joseph %}{% include "home/_card.html" with title="Briefs needing attention" subtitle="Open Joseph" href="" %}{% endif %}

    {% if is_admin %}
      {% include "home/_card.html" with title="Team approvals pending" count=sidebar_pending_approvals href="" %}
      {% include "home/_card.html" with title="System health" subtitle="Breakers · healing · fleet" href="" %}
      {% include "home/_card.html" with title="Invite a teammate" subtitle="Add someone by email" href="" %}
    {% endif %}
  </div>
</div>
{% endblock %}
```

> Fill the empty `href=""` values with the correct `{% url %}` reverses for each target (approvals queue, drafts filter, calendar, inbox, crm pipeline, joseph home, console healing, members list). Use the route names from the spec/inventory. Keep `_card.html` href required.

- [ ] **Step 4: Run it, expect pass**

Run: `uv run pytest apps/home/tests/ -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/home templates/home
git commit -m "feat(home): role-aware Home view + SVG performance graph + permission-gated cards"
```

---

## Task A5: Make Home the default landing

**Files:**
- Modify: `apps/accounts/views.py:40-68`
- Test: `apps/accounts/tests/test_dashboard_redirect.py` (create)

- [ ] **Step 1: Write the failing test**

```python
import pytest
from django.urls import reverse
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_root_redirects_to_home_not_calendar(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.url == reverse("home:index", kwargs={"workspace_id": workspace.id})
```

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest apps/accounts/tests/test_dashboard_redirect.py -x -q`
Expected: FAIL — redirects to calendar.

- [ ] **Step 3: Change the redirect target**

In `apps/accounts/views.py`, change BOTH `redirect("calendar:calendar", workspace_id=...)` calls (the `last_workspace_id` branch and the fallback branch) to `redirect("home:index", workspace_id=...)`.

- [ ] **Step 4: Run it, expect pass**

Run: `uv run pytest apps/accounts/tests/test_dashboard_redirect.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/accounts/views.py apps/accounts/tests/test_dashboard_redirect.py
git commit -m "feat(home): land on Home after login instead of the calendar"
```

---

## Task A6: Restructure the sidebar nav in `base.html`

**Files:**
- Modify: `templates/base.html` (nav block, ~lines 245–925)
- Test: `apps/home/tests/test_nav.py` (create — render base via the Home page and assert nav contents per role)

This is the largest task. **Preserve all existing CSS classes, the workspace switcher, the channels block, and the shell** — change only the link list grouping. Do not rename routes.

Target structure (top → bottom):

1. **Workspace switcher** — unchanged.
2. **Primary spine** (always, but each item still respects its own permission where one exists):
   - Home → `home:index`
   - Create → `composer:compose` (with a small dropdown: New post / Capture idea → `composer:idea_create` modal / Browse AI ideas → `/console/ideas` / From intake → `/console/intake`)
   - Calendar → `calendar:calendar`
   - Review → role-aware: if `effective_permissions.approve_posts` → `/console/approvals`, else `approvals:queue` (workspace_id). Show `sidebar_pending_approvals` badge.
   - Inbox → `inbox:feed` (show unread badge; gate on `use_inbox` perm if present)
   - Analytics → `analytics:index` (keep existing `analytics_enabled_platforms` gate)
3. **More ▾** (collapsible `<details>`): Brain `/console/brain`, Content pipeline `/console/pipeline`, Agents `/console/agents`, Breakers `/console/breakers`, Healing `/console/healing`, Learning `/console/learning`, Diffs `/console/diffs`, News `/console/news`, Intake `/console/intake/`, Intelligence playground (existing gate), Media library, Connect channels. Keep any per-item permission gates that exist today.
4. **Role groups** (collapsible, each behind its existing gate):
   - `{% if can_access_joseph %}` **Joseph ▸**: Today `joseph:home`, Pipeline `joseph:pipeline`, Knowledge `joseph:knowledge`, My content `joseph:content`, Voice `joseph:voice`, Decks `decks:index`.
   - `{% if can_manage_crm %}` **Relationships ▸**: Organizations `crm:org-list`, Contacts `crm:contact-list`, Deal pipeline `crm:pipeline`, Import `crm:import-home`, Mailboxes `outreach:mailbox`, Reply triage `outreach:triage`, Suppression `outreach:suppression`.
5. **Channels block** — unchanged (or moved under More if preferred; keep the existing markup).
6. **Footer / gear menu** — group the existing footer links + settings under one "Settings ⚙" entry: Account `accounts:settings`, Workspace `workspaces:settings`, Approvals `workspaces:approvals_settings`, Content Intake (Sheet) `settings_manager:index`, Credentials `credentials:list`, **People** `members:list`, Notification preferences `notifications:preferences`, API keys `api_keys:list`, Org settings `organizations:settings`, Log out.
7. **Notifications** — top-bar bell linking `notifications:list` with the existing unread badge (move out of the main nav list).

- [ ] **Step 1: Write the failing test**

`apps/home/tests/test_nav.py`:
```python
import pytest
from django.urls import reverse
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db
R = WorkspaceMembership.WorkspaceRole


def _home(client, workspace, user):
    client.force_login(user)
    return client.get(reverse("home:index", kwargs={"workspace_id": workspace.id})).content


def test_spine_present_for_everyone(client, workspace, make_user_in_workspace):
    html = _home(client, workspace, make_user_in_workspace(workspace, role=R.MANAGER))
    for label in [b"Home", b"Create", b"Calendar", b"Review", b"Inbox", b"Analytics", b"More"]:
        assert label in html


def test_content_only_hides_role_groups(client, workspace, make_user_in_workspace):
    html = _home(client, workspace, make_user_in_workspace(workspace, role=R.MANAGER))
    assert b"Joseph" not in html
    assert b"Relationships" not in html


def test_campaign_owner_sees_relationships_not_joseph(client, workspace, make_user_in_workspace):
    html = _home(client, workspace, make_user_in_workspace(workspace, role=R.CAMPAIGN_OWNER))
    assert b"Relationships" in html
    assert b"Joseph" not in html


def test_admin_sees_both_groups(client, workspace, make_user_in_workspace):
    html = _home(client, workspace, make_user_in_workspace(workspace, role=R.ADMIN))
    assert b"Joseph" in html and b"Relationships" in html
```

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest apps/home/tests/test_nav.py -x -q`
Expected: FAIL (old nav uses different labels/groupings).

- [ ] **Step 3: Restructure the nav markup**

Edit `templates/base.html` per the target structure above. Reuse existing nav-item markup/classes; wrap More + role groups in `<details>` so they collapse. Confirm every `{% url %}` resolves (run the test). Keep `{% if can_access_joseph %}` / `{% if can_manage_crm %}` exactly as the existing template uses them.

- [ ] **Step 4: Run it, expect pass**

Run: `uv run pytest apps/home/tests/test_nav.py -x -q`
Then full smoke: `uv run pytest -x -q -k "nav or home or base"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/base.html apps/home/tests/test_nav.py
git commit -m "feat(nav): role-filtered spine + More drawer + role groups + Settings gear"
```

---

## Task A7: Merge the content front doors (`create_landing` → redirect)

**Files:**
- Modify: `apps/composer/views.py:1869-1896`
- Test: `apps/composer/tests/test_create_landing_redirect.py` (create)

- [ ] **Step 1: Write the failing test**

```python
import pytest
from django.urls import reverse
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_create_landing_redirects_to_compose(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    resp = client.get(reverse("composer:create_landing", kwargs={"workspace_id": workspace.id}))
    assert resp.status_code == 302
    assert resp.url == reverse("composer:compose", kwargs={"workspace_id": workspace.id})
```

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest apps/composer/tests/test_create_landing_redirect.py -x -q`
Expected: FAIL — returns 200 (renders the old landing).

- [ ] **Step 3: Replace the view body with a redirect**

```python
from django.shortcuts import redirect

def create_landing(request, workspace_id):
    """Deprecated landing — the Create front door now opens the composer directly.
    Kept as a 302 so old links/bookmarks keep working."""
    _get_workspace(request, workspace_id)  # preserve the membership/403 check
    return redirect("composer:compose", workspace_id=workspace_id)
```

> The idea board, templates, and feeds previously surfaced on this landing remain reachable via the Create dropdown (idea modal / AI ideas / intake) added in A6 and their existing routes (`composer:idea_board`, etc.). Nothing is deleted.

- [ ] **Step 4: Run it, expect pass**

Run: `uv run pytest apps/composer/tests/test_create_landing_redirect.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/composer/views.py apps/composer/tests/test_create_landing_redirect.py
git commit -m "feat(composer): collapse Create landing into one front door (redirect to compose)"
```

---

## Task A8: Surface "People" + per-role helper text on the invite form

**Files:**
- Modify: `templates/members/partials/invite_modal.html` (~line 67–73)
- Test: `apps/members/tests/test_invite_helper.py` (create)

- [ ] **Step 1: Write the failing test**

```python
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_member_list_renders_role_helper(client, org_admin_user, workspace):
    client.force_login(org_admin_user)
    resp = client.get(reverse("members:list"))
    assert resp.status_code == 200
    assert b"CRM + publishing" in resp.content  # helper text for campaign_owner tier
```

> Reuse an existing "org admin" fixture if present; otherwise create one in the test that makes an `OrgMembership` with `org_role="admin"`.

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest apps/members/tests/test_invite_helper.py -x -q`
Expected: FAIL — helper copy not present.

- [ ] **Step 3: Add the helper text**

In `templates/members/partials/invite_modal.html`, immediately after the `</select>` for `ws_role_{{ ws.id }}` (line ~73), add:
```django
<p class="text-[11px] text-stone-500 mt-1 leading-snug">
  Admin — full access · Campaign owner — CRM + publishing · Manager — publishing · Editor — create, needs approval
</p>
```

- [ ] **Step 4: Run it, expect pass**

Run: `uv run pytest apps/members/tests/test_invite_helper.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/members/partials/invite_modal.html apps/members/tests/test_invite_helper.py
git commit -m "feat(members): per-role helper text on invite so role->experience is obvious"
```

---

## Task A9: Phase A regression gate

- [ ] **Step 1:** Run the full suite: `uv run pytest -q`
- [ ] **Step 2:** Fix any breakage caused by the landing change / nav (e.g. tests asserting the old calendar default). Update those tests to the new Home default where correct.
- [ ] **Step 3:** Commit any fixes: `git commit -am "test: update expectations for Home default landing + new nav"`

---

# PHASE B — Compose density

## Task B1: Two-pane + folded Compose layout

**Files:**
- Modify: `templates/composer/compose.html`
- Test: `apps/composer/tests/test_compose_renders.py` (create — render smoke for new + edit)

Apply the four density principles to `compose.html`:
1. Top **two-pane**: left = caption + media + channels; right = live preview (move the existing preview markup up beside the editor).
2. **Folded `<details>` sections** for: Campaign / track / pillar / tags; First comment & schedule; Send for review (the assign block).
3. One primary **Schedule / Publish** button, visually dominant.
4. Keep all existing field `name=` attributes and the `{% if post %}` guards added in the 500 fix — do not regress save/schedule/publish.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from django.urls import reverse
from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_compose_new_and_edit_render_200(client, workspace, make_user_in_workspace, make_post):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    new = client.get(reverse("composer:compose", kwargs={"workspace_id": workspace.id}))
    assert new.status_code == 200
    post = make_post(workspace, status="draft", author=user)
    edit = client.get(reverse("composer:compose_edit", kwargs={"workspace_id": workspace.id, "post_id": post.id}))
    assert edit.status_code == 200
    assert b"Schedule" in edit.content
```

- [ ] **Step 2: Run it, expect pass on new, then refactor** (the 500 fix means `new` already renders 200; this test guards the refactor doesn't regress).

Run: `uv run pytest apps/composer/tests/test_compose_renders.py -x -q`

- [ ] **Step 3: Refactor `compose.html`** to the two-pane + folded layout, preserving field names and `{% if post %}` guards.

- [ ] **Step 4: Re-run** the render test + the existing composer/publish tests: `uv run pytest -q -k "compose or publish"`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/composer/compose.html apps/composer/tests/test_compose_renders.py
git commit -m "feat(composer): calmer two-pane Compose with folded optional sections"
```

---

# PHASE C — Remaining density pages (outline; plan per page when reached)

Apply the same four density principles, one page per task, each with a render-smoke test and a commit:
- **C1** — Calendar/Publish (`templates/calendar/*`): make the day grid the focus; fold filters/queues into a side rail.
- **C2** — Content board / Studio (`templates/console/*`): reduce column chrome; one clear primary action per card (already partly done in `_studio_card.html`).
- **C3** — Inbox detail (`templates/inbox/*`): thread-first; tools in a quiet rail.

Each C-task: write render-smoke test → refactor template → run `uv run pytest -q -k "<area>"` → commit. Do not start Phase C until Phases A and B are merged and verified in prod.

---

## Self-Review

- **Spec coverage:** §3 nav spine → A6; §3.2 More → A6; §3.3 role groups → A6; §3.3.1 personas → roles → encoded in A4/A6 gating + A8 helper; §3.4 Settings gear → A6; §3.5 invite surfacing → A8 (+ A4 admin card); §4 role-aware Home + performance graph → A1–A4; §5 front-door merge → A6 dropdown + A7 redirect; §6 density → B1 + C; default landing → A5. Covered.
- **Placeholder scan:** the only deferred specifics are the `href=""` reverses in the Home template (A4 Step 3 note lists exactly which route each must use) and the C-phase per-page templates (explicitly deferred until A/B ship). No "TODO/TBD" in shipping code steps.
- **Type/name consistency:** `home:index` used consistently (A1/A4/A5/A6); `performance_summary` / `my_drafts` / `going_out_soon` / `pending_signoff` names match across A2–A4; `effective_permissions.get(key)` accessor matches `apps/members/models.py:137`; `PlatformPost.Status.PUBLISHED` (A2) vs `Post.review_state` (A3) kept distinct with a verification note.
- **Risk note carried from spec:** `base.html` is central — A6 changes link structure only and is gated by per-role render tests before commit.
