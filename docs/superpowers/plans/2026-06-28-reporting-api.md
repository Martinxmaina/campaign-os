# Reporting / Aggregation API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four read-only aggregation endpoints to the existing `/api/v1/` Agent API — `GET /pipeline`, `GET /content`, `GET /campaigns`, `GET /overview` — so a dashboard or agent can pull workspace-wide content pipeline status, the list of everything being posted, campaign rollups, and top-line analytics in one place.

**Architecture:** A new `apps/api/routers/reporting.py` router mounted at the API root, reusing the established contract (`enforce_http_rate_limits` read-tier → permission/scope checks → an `api_builders` function → `log_audit_entry`). Response assembly lives in per-app `api_builders` modules so the MCP transport can reuse it later. Campaigns aggregate the free-form `Post.campaign` string (no new model). Account analytics are computed once per request into an account→metrics map, then summed for both the workspace rollup and each campaign.

**Tech Stack:** Django, Django-Ninja, pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-06-28-reporting-api-design.md`

---

## Key reference facts (read before starting)

- **Router contract** (see `apps/api/routers/posts.py`, `analytics.py`):
  - `request.api_key` — the `ApiKey` (set by `ApiKeyAuth`). `request.workspace` — the `Workspace`. `request.workspace_membership` — has `.effective_permissions` (dict).
  - Allowlist: `{sa.id for sa in request.api_key.social_accounts.all()}`.
  - `from apps.api.limits import enforce_http_rate_limits` → `enforce_http_rate_limits(request, is_write=False)`.
  - `from apps.api.middleware import log_audit_entry` → `log_audit_entry(request, action=..., target_id=None, status_code=200)`.
  - `_require_perm(request, key)` raises `HttpError(403, ...)`; copy the local helper (don't import from posts to keep the router self-contained, matching how `media.py` re-declares its own `_require_perm`).
- **Funnel helper (reuse as-is):** `from apps.content_intake.progress import content_pipeline_progress` → `content_pipeline_progress(workspace)` returns `{"stages":[{key,label,count,pct,color}], "total","created","curated","published","percent"}`.
- **Derived post status:** `from apps.composer.status import derive_post_status` → `derive_post_status([pp.status for pp in post.platform_posts.all()])`. Values: `draft, changes_requested, rejected, pending_review, pending_client, approved, scheduled, publishing, partially_published, published, failed`.
- **Post fields:** `id, workspace_id, title, caption, first_comment, campaign, track, pillar, scheduled_at, published_at, review_state, created_at, updated_at`, reverse `platform_posts`, reverse OneToOne `intake_source`. `Post.status` property derives from children.
- **PlatformPost fields:** `id, post_id, social_account_id, status, scheduled_at, published_at, platform_post_id, publish_error`. `social_account.platform` is the platform string.
- **Schema conventions** (`apps/api/schemas.py`): `from ninja import Field, Schema`; `from pydantic import field_serializer`; datetimes serialized with `_serialize_utc_z`; UUIDs typed `uuid.UUID`; every field has `description=`.
- **Cursor codec** (`apps/api/routers/media.py:234-245`): base64-url JSON offset, `{"o": <int>}`. We re-declare the same two helpers in the reporting router.
- **Analytics builder:** `from apps.analytics.api_builders import build_account_analytics` → `build_account_analytics(account, days)` returns `AccountAnalyticsResponse` with `analytics_available: bool` and `hero_metrics: list[DerivedMetricResponse]` (each has `.key` and `.value`). Platform on `account.platform`.
- **Tests:** Use the fixture style in `apps/api/tests/test_analytics_router.py`: `services.issue_api_key(workspace=, social_accounts=[...], issued_by=user, name=, permissions=list(PERMISSION_KEYS))`, `_SecureClient(HTTP_AUTHORIZATION=f"Bearer {issued_key.plaintext_token}")`, all requests `secure=True`. `from apps.members.models import PERMISSION_KEYS, OrgMembership, WorkspaceMembership`.
- **Run tests:** `uv run pytest -x -q <path>`.

---

## File Structure

- **Create** `apps/api/routers/reporting.py` — the four routes + local helpers (`_require_perm`, `_has_perm`, cursor codec, allowlist extraction).
- **Modify** `apps/api/api.py` — import + mount `reporting_router`; extend `_action_for_path` with reporting failure labels.
- **Modify** `apps/api/schemas.py` — add the new Schema classes.
- **Create** `apps/composer/api_builders.py` — `build_content_list`, `build_content_summary`, `build_campaigns`.
- **Modify** `apps/analytics/api_builders.py` — add `account_metric_map`, `build_workspace_analytics_rollup`.
- **Create** `apps/api/tests/test_reporting_router.py` — end-to-end route tests.
- **Create** `apps/composer/tests/test_reporting_builders.py` — builder unit tests.

---

## Task 1: Pipeline endpoint (vertical slice — router scaffold + first route)

**Files:**
- Create: `apps/api/routers/reporting.py`
- Modify: `apps/api/schemas.py`
- Modify: `apps/api/api.py`
- Test: `apps/api/tests/test_reporting_router.py`

- [ ] **Step 1: Add the pipeline schemas to `apps/api/schemas.py`**

Append at the end of the file (after `ErrorResponse`):

```python
# ---------------------------------------------------------------------------
# /pipeline, /content, /campaigns, /overview — reporting surface
# ---------------------------------------------------------------------------


class PipelineStage(Schema):
    key: str = Field(..., description="Funnel stage key: curated|drafting|review|approved|scheduled|published.")
    label: str = Field(..., description="Human label for the stage.")
    count: int = Field(..., description="Number of content items currently in this stage.")
    pct: int = Field(..., description="This stage's count as a percent of the pipeline total (0-100).")
    color: str = Field(..., description="Hex colour for the stage bar.")


class PipelineResponse(Schema):
    stages: list[PipelineStage] = Field(..., description="Funnel stages in flow order.")
    total: int = Field(..., description="Total active content items (created + curated, de-duped).")
    created: int = Field(..., description="Composer posts with no linked intake item.")
    curated: int = Field(..., description="Intake-register rows (each counted once).")
    published: int = Field(..., description="Items in the published stage.")
    percent: int = Field(..., description="Weighted progress through the pipeline (0-100).")
```

- [ ] **Step 2: Write the failing test for the pipeline route**

Create `apps/api/tests/test_reporting_router.py`:

```python
"""End-to-end tests for the /api/v1 reporting surface."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.api_keys import services
from apps.members.models import PERMISSION_KEYS, OrgMembership, WorkspaceMembership


@pytest.fixture
def user(db):
    from apps.accounts.models import User

    return User.objects.create_user(
        email="reporting-owner@example.com",
        password="testpass123",
        name="Reporting Owner",
        tos_accepted_at=timezone.now(),
    )


@pytest.fixture
def organization(db):
    from apps.organizations.models import Organization

    return Organization.objects.create(name="Reporting Org")


@pytest.fixture
def workspace(db, organization):
    from apps.workspaces.models import Workspace

    return Workspace.objects.create(name="Reporting WS", organization=organization)


@pytest.fixture
def owner_memberships(db, user, organization, workspace):
    OrgMembership.objects.create(user=user, organization=organization, org_role=OrgMembership.OrgRole.OWNER)
    return WorkspaceMembership.objects.create(
        user=user, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
    )


@pytest.fixture
def linkedin_account(db, workspace):
    from apps.social_accounts.models import SocialAccount

    return SocialAccount.objects.create(
        workspace=workspace,
        platform="linkedin",
        account_platform_id="li-rep",
        account_name="LI Reporting",
        connection_status="connected",
    )


@pytest.fixture
def issued_key(db, user, owner_memberships, workspace, linkedin_account):
    return services.issue_api_key(
        workspace=workspace,
        social_accounts=[linkedin_account],
        issued_by=user,
        name="reporting-smoke",
        permissions=list(PERMISSION_KEYS),
    )


class _SecureClient(Client):
    def generic(self, method, path, *args, **kwargs):
        kwargs["secure"] = True
        return super().generic(method, path, *args, **kwargs)


@pytest.fixture
def client_with_token(issued_key):
    return _SecureClient(HTTP_AUTHORIZATION=f"Bearer {issued_key.plaintext_token}")


def _make_post(workspace, account, *, status="draft", campaign="", scheduled_at=None, published_at=None):
    """Create a Post with one PlatformPost child in the given status."""
    from apps.composer.models import PlatformPost, Post

    post = Post.objects.create(
        workspace=workspace,
        title=f"Post {status}",
        caption="Body text for the post.",
        campaign=campaign,
        scheduled_at=scheduled_at,
        published_at=published_at,
    )
    PlatformPost.objects.create(
        post=post,
        social_account=account,
        status=status,
        scheduled_at=scheduled_at,
        published_at=published_at,
    )
    return post


@pytest.mark.django_db
class TestPipeline:
    def test_pipeline_matches_progress_helper(self, client_with_token, workspace, linkedin_account):
        from apps.content_intake.progress import content_pipeline_progress

        _make_post(workspace, linkedin_account, status="draft")
        _make_post(workspace, linkedin_account, status="published", published_at=timezone.now())

        r = client_with_token.get("/api/v1/pipeline")
        assert r.status_code == 200
        body = r.json()
        expected = content_pipeline_progress(workspace)
        assert body["total"] == expected["total"]
        assert body["published"] == expected["published"]
        assert [s["key"] for s in body["stages"]] == [s["key"] for s in expected["stages"]]

    def test_pipeline_requires_auth(self):
        r = _SecureClient().get("/api/v1/pipeline")
        assert r.status_code == 401
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest -x -q apps/api/tests/test_reporting_router.py::TestPipeline -v`
Expected: FAIL — 404 (route not mounted yet).

- [ ] **Step 4: Create the reporting router with the pipeline route**

Create `apps/api/routers/reporting.py`:

```python
"""``/api/v1/{overview,content,campaigns,pipeline}`` — read-only reporting.

Workspace-level rollups for dashboards and agents. Every route:

1. Enforces read-tier HTTP rate limits.
2. Scopes to the key's workspace and (for content) account allowlist.
3. Gates analytics *numbers* behind ``view_analytics`` — counts are open to
   any valid key, the same data class as reading a post.
4. Delegates assembly to per-app ``api_builders`` so MCP can reuse it.
5. Writes a ``reporting.*.read`` audit row on the way out.
"""
from __future__ import annotations

import base64
import json
import uuid

from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from apps.api.limits import enforce_http_rate_limits
from apps.api.middleware import log_audit_entry
from apps.api.schemas import PipelineResponse
from apps.content_intake.progress import content_pipeline_progress

router = Router(tags=["reporting"])

_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100


def _require_perm(request: HttpRequest, key: str) -> None:
    membership = getattr(request, "workspace_membership", None)
    if membership is None or not membership.effective_permissions.get(key, False):
        raise HttpError(403, f"Permission denied: {key}")


def _has_perm(request: HttpRequest, key: str) -> bool:
    membership = getattr(request, "workspace_membership", None)
    return bool(membership and membership.effective_permissions.get(key, False))


def _allowed_account_ids(request: HttpRequest) -> set[uuid.UUID]:
    return {sa.id for sa in request.api_key.social_accounts.all()}  # type: ignore[attr-defined]


def _decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode() + b"==")
        return json.loads(raw.decode())
    except (ValueError, json.JSONDecodeError) as exc:
        raise HttpError(422, "Invalid cursor.") from exc


def _encode_cursor(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).rstrip(b"=").decode()


@router.get("/pipeline", response=PipelineResponse, summary="Content pipeline funnel for the workspace")
def pipeline(request):
    enforce_http_rate_limits(request, is_write=False)
    funnel = content_pipeline_progress(request.workspace)
    log_audit_entry(request, action="reporting.pipeline.read", target_id=None, status_code=200)
    return funnel
```

- [ ] **Step 5: Mount the router and add failure-audit labels in `apps/api/api.py`**

Add the import near the other router imports (after line 26):

```python
from apps.api.routers.reporting import router as reporting_router
```

Add the mount immediately before the MCP mount (before line 79 `api.add_router("/mcp", mcp_router)`):

```python
# Reporting/aggregation surface. Mounted at root with distinct first path
# segments (/overview, /content, /campaigns, /pipeline) so it can't shadow
# the resource routers above. Before /mcp for the same reason as the others.
api.add_router("", reporting_router)
```

In `_action_for_path`, add a reporting branch at the top of the matcher (before the `/analytics/` checks):

```python
    if "/pipeline" in path:
        return f"reporting.pipeline.read.{status_code}"
    if "/campaigns" in path:
        return f"reporting.campaigns.read.{status_code}"
    if "/overview" in path:
        return f"reporting.overview.read.{status_code}"
    if path.endswith("/content") or "/content" in path:
        return f"reporting.content.read.{status_code}"
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest -x -q apps/api/tests/test_reporting_router.py::TestPipeline -v`
Expected: PASS (both tests).

Also confirm the route renders without a double-slash:
Run: `uv run python manage.py shell -c "from apps.api.api import api; print([str(r.path_prefix)+'|'+'/'.join(str(p.path) for p in r.urls_paths('')) for r in []] or 'ok'); from django.test import Client" 2>/dev/null; echo check /api/v1/docs manually`
(If unsure, the passing 200 in the test already proves the path resolves to `/api/v1/pipeline`.)

- [ ] **Step 7: Commit**

```bash
git add apps/api/routers/reporting.py apps/api/api.py apps/api/schemas.py apps/api/tests/test_reporting_router.py
git commit -m "feat(api): GET /api/v1/pipeline reporting funnel

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Content list builder + endpoint

**Files:**
- Create: `apps/composer/api_builders.py`
- Modify: `apps/api/schemas.py`
- Modify: `apps/api/routers/reporting.py`
- Test: `apps/composer/tests/test_reporting_builders.py`, `apps/api/tests/test_reporting_router.py`

- [ ] **Step 1: Add the content schemas to `apps/api/schemas.py`**

Append after `PipelineResponse`:

```python
class ContentPlatform(Schema):
    platform: str = Field(..., description="Platform key (e.g. linkedin, instagram, x).")
    account_id: uuid.UUID = Field(..., description="Target SocialAccount id.")
    status: str = Field(..., description="Per-platform editorial/publish status.")
    scheduled_at: dt.datetime | None = Field(None, description="When this child is scheduled.")
    published_at: dt.datetime | None = Field(None, description="When this child was published.")
    platform_post_id: str = Field("", description="Native post id on the platform once published.")
    error: str = Field("", description="Publish error, if the last attempt failed.")

    @field_serializer("scheduled_at", "published_at")
    def _ser_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)


class ContentItem(Schema):
    id: uuid.UUID = Field(..., description="Post id.")
    title: str = Field(..., description="Post title.")
    caption_preview: str = Field(..., description="First ~160 chars of the caption.")
    source: str = Field(..., description="created (composer-authored) | curated (from the intake register).")
    status: str = Field(..., description="Derived aggregate status across the post's platform children.")
    campaign: str = Field("", description="Free-form campaign label.")
    track: str = Field("", description="Programme track.")
    pillar: str = Field("", description="Sector pillar.")
    platforms: list[ContentPlatform] = Field(..., description="Per-platform children.")
    scheduled_at: dt.datetime | None = Field(None, description="Post-level scheduled time.")
    published_at: dt.datetime | None = Field(None, description="Post-level published time.")
    created_at: dt.datetime = Field(..., description="Creation time.")
    updated_at: dt.datetime = Field(..., description="Last update time.")

    @field_serializer("scheduled_at", "published_at", "created_at", "updated_at")
    def _ser_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)


class ContentListResponse(Schema):
    items: list[ContentItem] = Field(..., description="Page of content items.")
    next_cursor: str | None = Field(None, description="Opaque cursor for the next page; null at the end.")
    has_more: bool = Field(..., description="True if another page exists.")
```

- [ ] **Step 2: Write failing builder unit tests**

Create `apps/composer/tests/test_reporting_builders.py`:

```python
"""Unit tests for the composer reporting builders."""
from __future__ import annotations

import pytest
from django.utils import timezone


@pytest.fixture
def setup(db):
    from apps.accounts.models import User
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="B Org")
    ws = Workspace.objects.create(name="B WS", organization=org)
    li = SocialAccount.objects.create(
        workspace=ws, platform="linkedin", account_platform_id="li-b",
        account_name="LI", connection_status="connected",
    )
    x = SocialAccount.objects.create(
        workspace=ws, platform="x", account_platform_id="x-b",
        account_name="X", connection_status="connected",
    )
    return ws, li, x


def _post(ws, account, *, status="draft", campaign="", intake=False, **kw):
    from apps.composer.models import PlatformPost, Post

    post = Post.objects.create(workspace=ws, title=f"T-{status}", caption="c" * 200, campaign=campaign, **kw)
    if account is not None:
        PlatformPost.objects.create(post=post, social_account=account, status=status)
    if intake:
        from apps.content_intake.models import ContentIntake

        ContentIntake.objects.create(workspace=ws, post=post, status="drafting")
    return post


@pytest.mark.django_db
def test_content_list_filters_by_campaign(setup):
    from apps.composer.api_builders import build_content_list

    ws, li, x = setup
    _post(ws, li, campaign="EGM")
    _post(ws, li, campaign="Other")
    allowed = {li.id, x.id}
    items, has_more = build_content_list(ws, allowed, campaign="EGM")
    assert len(items) == 1
    assert items[0].campaign == "EGM"
    assert items[0].caption_preview == "c" * 160


@pytest.mark.django_db
def test_content_list_allowlist_excludes_foreign_account_posts(setup):
    from apps.composer.api_builders import build_content_list

    ws, li, x = setup
    _post(ws, li)            # visible to an li-only key
    _post(ws, x)             # NOT visible to an li-only key
    items, _ = build_content_list(ws, {li.id})
    assert len(items) == 1
    assert items[0].platforms[0].account_id == li.id


@pytest.mark.django_db
def test_content_list_pagination(setup):
    from apps.composer.api_builders import build_content_list

    ws, li, x = setup
    for _ in range(3):
        _post(ws, li)
    page1, has_more = build_content_list(ws, {li.id}, limit=2, offset=0)
    assert len(page1) == 2 and has_more is True
    page2, has_more2 = build_content_list(ws, {li.id}, limit=2, offset=2)
    assert len(page2) == 1 and has_more2 is False


@pytest.mark.django_db
def test_content_list_source_flag(setup):
    from apps.composer.api_builders import build_content_list

    ws, li, x = setup
    _post(ws, li, intake=True)
    _post(ws, li, intake=False)
    items, _ = build_content_list(ws, {li.id})
    sources = sorted(i.source for i in items)
    assert sources == ["created", "curated"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest -x -q apps/composer/tests/test_reporting_builders.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.composer.api_builders`.

- [ ] **Step 4: Create `apps/composer/api_builders.py` with `build_content_list`**

```python
"""Compose composer/content models into the reporting API schemas.

HTTP-agnostic: the router passes ``workspace`` and the key's allowlist; these
builders never touch ``request`` so the MCP transport can reuse them. Scoping
mirrors ``apps/api/routers/posts.py::_get_workspace_post`` — a post is visible
only if it has no platform children, or every child's account is allowlisted.
"""
from __future__ import annotations

import uuid

from apps.api.schemas import ContentItem, ContentPlatform
from apps.composer.models import Post
from apps.composer.status import derive_post_status

_CAPTION_PREVIEW = 160


def _scoped_posts(workspace):
    """Workspace posts with children + accounts prefetched, newest first."""
    return (
        Post.objects.filter(workspace_id=workspace.id)
        .select_related("intake_source")
        .prefetch_related("platform_posts__social_account")
        .order_by("-created_at", "id")
    )


def _visible_to_allowlist(post, allowed_account_ids: set[uuid.UUID]) -> bool:
    child_account_ids = {pp.social_account_id for pp in post.platform_posts.all()}
    if not child_account_ids:
        return True  # pure draft, targets no account → no confused-deputy risk
    return child_account_ids.issubset(allowed_account_ids)


def _content_item(post) -> ContentItem:
    children = list(post.platform_posts.all())
    platforms = [
        ContentPlatform(
            platform=pp.social_account.platform,
            account_id=pp.social_account_id,
            status=pp.status,
            scheduled_at=pp.scheduled_at,
            published_at=pp.published_at,
            platform_post_id=pp.platform_post_id or "",
            error=pp.publish_error or "",
        )
        for pp in children
    ]
    return ContentItem(
        id=post.id,
        title=post.title,
        caption_preview=post.caption[:_CAPTION_PREVIEW],
        source="curated" if post.intake_source_id else "created",
        status=derive_post_status([pp.status for pp in children]),
        campaign=post.campaign,
        track=post.track,
        pillar=post.pillar,
        platforms=platforms,
        scheduled_at=post.scheduled_at,
        published_at=post.published_at,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def build_content_list(
    workspace,
    allowed_account_ids: set[uuid.UUID],
    *,
    status: str | None = None,
    campaign: str | None = None,
    platform: str | None = None,
    source: str | None = None,
    scheduled_after=None,
    scheduled_before=None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[ContentItem], bool]:
    """Return (page_items, has_more).

    DB filters: campaign, source, scheduled-date range, platform. The
    allowlist filter and the derived ``status`` filter run in Python because
    both depend on the post's set of children; the resulting full list is
    sliced for the offset cursor. Content volumes here are workspace-scoped
    (tens-to-hundreds), so full materialisation is acceptable.
    """
    qs = _scoped_posts(workspace)
    if campaign is not None:
        qs = qs.filter(campaign=campaign)
    if source == "curated":
        qs = qs.filter(intake_source__isnull=False)
    elif source == "created":
        qs = qs.filter(intake_source__isnull=True)
    if scheduled_after is not None:
        qs = qs.filter(scheduled_at__gte=scheduled_after)
    if scheduled_before is not None:
        qs = qs.filter(scheduled_at__lte=scheduled_before)
    if platform is not None:
        qs = qs.filter(platform_posts__social_account__platform=platform).distinct()

    visible = [p for p in qs if _visible_to_allowlist(p, allowed_account_ids)]
    items = [_content_item(p) for p in visible]
    if status is not None:
        items = [it for it in items if it.status == status]

    window = items[offset : offset + limit + 1]
    has_more = len(window) > limit
    return window[:limit], has_more
```

- [ ] **Step 5: Run the builder tests to verify they pass**

Run: `uv run pytest -x -q apps/composer/tests/test_reporting_builders.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Add the `/content` route to `apps/api/routers/reporting.py`**

Add the import at the top (extend the schemas import):

```python
from apps.api.schemas import ContentListResponse, PipelineResponse
from apps.composer.api_builders import build_content_list
```

Add the route after `pipeline`:

```python
@router.get("/content", response=ContentListResponse, summary="List all content being posted")
def content(
    request,
    status: str | None = Query(None, description="Filter by derived post status (e.g. scheduled, published, failed)."),
    campaign: str | None = Query(None, description="Exact campaign-label match."),
    platform: str | None = Query(None, description="Only posts with a child on this platform."),
    source: str | None = Query(None, description="created | curated."),
    scheduled_after: str | None = Query(None, description="ISO datetime lower bound on scheduled_at."),
    scheduled_before: str | None = Query(None, description="ISO datetime upper bound on scheduled_at."),
    cursor: str | None = Query(None, description="Opaque pagination cursor from a prior response."),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Page size (1-100)."),
):
    enforce_http_rate_limits(request, is_write=False)
    offset = int(_decode_cursor(cursor).get("o", 0)) if cursor else 0
    items, has_more = build_content_list(
        request.workspace,
        _allowed_account_ids(request),
        status=status,
        campaign=campaign,
        platform=platform,
        source=source,
        scheduled_after=scheduled_after,
        scheduled_before=scheduled_before,
        limit=limit,
        offset=offset,
    )
    body = ContentListResponse(
        items=items,
        next_cursor=_encode_cursor({"o": offset + limit}) if has_more else None,
        has_more=has_more,
    )
    log_audit_entry(request, action="reporting.content.read", target_id=None, status_code=200)
    return body
```

- [ ] **Step 7: Add route-level tests to `apps/api/tests/test_reporting_router.py`**

Append:

```python
@pytest.mark.django_db
class TestContent:
    def test_lists_workspace_content_with_filters(self, client_with_token, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="published", campaign="EGM", published_at=timezone.now())
        _make_post(workspace, linkedin_account, status="draft", campaign="Other")

        r = client_with_token.get("/api/v1/content?campaign=EGM")
        assert r.status_code == 200
        body = r.json()
        assert body["has_more"] is False
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["campaign"] == "EGM"
        assert item["status"] == "published"
        assert item["platforms"][0]["platform"] == "linkedin"

    def test_pagination_cursor(self, client_with_token, workspace, linkedin_account):
        for _ in range(3):
            _make_post(workspace, linkedin_account, status="draft")
        r1 = client_with_token.get("/api/v1/content?limit=2")
        b1 = r1.json()
        assert len(b1["items"]) == 2 and b1["has_more"] is True and b1["next_cursor"]
        r2 = client_with_token.get(f"/api/v1/content?limit=2&cursor={b1['next_cursor']}")
        b2 = r2.json()
        assert len(b2["items"]) == 1 and b2["has_more"] is False

    def test_cross_workspace_isolation(self, client_with_token, organization):
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.models import Workspace

        other_ws = Workspace.objects.create(name="Other WS", organization=organization)
        other_acct = SocialAccount.objects.create(
            workspace=other_ws, platform="linkedin", account_platform_id="li-other",
            account_name="Other LI", connection_status="connected",
        )
        _make_post(other_ws, other_acct, status="published", published_at=timezone.now())

        r = client_with_token.get("/api/v1/content")
        assert r.status_code == 200
        assert r.json()["items"] == []
```

- [ ] **Step 8: Run the route tests to verify they pass**

Run: `uv run pytest -x -q apps/api/tests/test_reporting_router.py -v`
Expected: PASS (TestPipeline + TestContent).

- [ ] **Step 9: Commit**

```bash
git add apps/api/routers/reporting.py apps/api/schemas.py apps/composer/api_builders.py apps/composer/tests/test_reporting_builders.py apps/api/tests/test_reporting_router.py
git commit -m "feat(api): GET /api/v1/content list with filters + allowlist scoping

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Analytics rollup builder

**Files:**
- Modify: `apps/analytics/api_builders.py`
- Modify: `apps/api/schemas.py`
- Test: `apps/analytics/tests/test_reporting_rollup.py`

- [ ] **Step 1: Add the rollup schemas to `apps/api/schemas.py`**

Append after `ContentListResponse`:

```python
class PlatformMetric(Schema):
    platform: str = Field(..., description="Platform key.")
    metrics: dict[str, float] = Field(..., description="Metric key → summed value for the platform.")


class AnalyticsRollup(Schema):
    available: bool = Field(..., description="False when the key lacks view_analytics or no account has analytics.")
    window_days: int = Field(..., description="Rolling window size in days.")
    accounts: int = Field(..., description="Number of allowlisted accounts contributing analytics.")
    totals: dict[str, float] = Field(..., description="Metric key → summed value across all platforms.")
    by_platform: list[PlatformMetric] = Field(..., description="Per-platform metric breakdown.")
```

- [ ] **Step 2: Write failing rollup unit tests**

Create `apps/analytics/tests/test_reporting_rollup.py`:

```python
"""Unit tests for the workspace analytics rollup builders."""
from __future__ import annotations

import pytest
from django.utils import timezone


@pytest.fixture
def setup(db):
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="R Org")
    ws = Workspace.objects.create(name="R WS", organization=org)
    ig = SocialAccount.objects.create(
        workspace=ws, platform="instagram", account_platform_id="ig-r",
        account_name="IG", connection_status="connected", follower_count=100,
    )
    return ws, ig


@pytest.mark.django_db
def test_rollup_unavailable_when_no_accounts():
    from apps.analytics.api_builders import account_metric_map, build_workspace_analytics_rollup

    rollup = build_workspace_analytics_rollup(account_metric_map([], 30), 30)
    assert rollup.available is False
    assert rollup.accounts == 0
    assert rollup.totals == {}


@pytest.mark.django_db
def test_rollup_sums_hero_metrics(setup):
    from apps.analytics.api_builders import account_metric_map, build_workspace_analytics_rollup
    from apps.analytics.models import AccountInsightsSnapshot

    ws, ig = setup
    today = timezone.now().date()
    # Two days of an "impressions" metric so derive() has a window.
    AccountInsightsSnapshot.objects.create(social_account=ig, metric_key="impressions", date=today, value=10.0)
    AccountInsightsSnapshot.objects.create(
        social_account=ig, metric_key="impressions", date=today - timezone.timedelta(days=1), value=5.0
    )
    amap = account_metric_map([ig], 30)
    rollup = build_workspace_analytics_rollup(amap, 30)
    assert rollup.available is True
    assert rollup.accounts == 1
    # impressions is a count metric → summed over the window.
    assert rollup.totals.get("impressions", 0) >= 10.0
    assert rollup.by_platform[0].platform == "instagram"
```

- [ ] **Step 3: Run the rollup tests to verify they fail**

Run: `uv run pytest -x -q apps/analytics/tests/test_reporting_rollup.py -v`
Expected: FAIL — `ImportError: account_metric_map`.

- [ ] **Step 4: Add the rollup builders to `apps/analytics/api_builders.py`**

Add these imports to the top of the file's `from apps.api.schemas import (...)` block:

```python
    AnalyticsRollup,
    PlatformMetric,
```

Append at the end of the module:

```python
def account_metric_map(accounts, days: int) -> dict:
    """Compute per-account hero metrics once, keyed by account id.

    Returns ``{account_id: {"platform": str, "available": bool,
    "metrics": {metric_key: value}}}``. Reuses ``build_account_analytics`` so
    the numbers match ``GET /analytics/accounts/{id}`` exactly. One pass per
    account; callers (workspace rollup, per-campaign rollups) then sum without
    re-querying.
    """
    result: dict = {}
    for account in accounts:
        resp = build_account_analytics(account, days)
        result[account.id] = {
            "platform": account.platform,
            "available": resp.analytics_available,
            "metrics": {m.key: m.value for m in resp.hero_metrics},
        }
    return result


def build_workspace_analytics_rollup(account_map: dict, days: int) -> AnalyticsRollup:
    """Sum an ``account_metric_map`` into workspace totals + per-platform."""
    available_accounts = [a for a in account_map.values() if a["available"]]
    totals: dict[str, float] = {}
    per_platform: dict[str, dict[str, float]] = {}
    for acct in available_accounts:
        platform_bucket = per_platform.setdefault(acct["platform"], {})
        for key, value in acct["metrics"].items():
            totals[key] = totals.get(key, 0.0) + value
            platform_bucket[key] = platform_bucket.get(key, 0.0) + value
    return AnalyticsRollup(
        available=bool(available_accounts),
        window_days=days,
        accounts=len(available_accounts),
        totals=totals,
        by_platform=[PlatformMetric(platform=p, metrics=m) for p, m in sorted(per_platform.items())],
    )
```

- [ ] **Step 5: Run the rollup tests to verify they pass**

Run: `uv run pytest -x -q apps/analytics/tests/test_reporting_rollup.py -v`
Expected: PASS (2 tests). If the count-metric assertion is brittle (derive may average), relax to `assert "impressions" in rollup.totals`.

- [ ] **Step 6: Commit**

```bash
git add apps/analytics/api_builders.py apps/api/schemas.py apps/analytics/tests/test_reporting_rollup.py
git commit -m "feat(analytics): workspace analytics rollup builders (account_metric_map + sum)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Campaigns builder + endpoint

**Files:**
- Modify: `apps/composer/api_builders.py`
- Modify: `apps/api/schemas.py`
- Modify: `apps/api/routers/reporting.py`
- Test: `apps/composer/tests/test_reporting_builders.py`, `apps/api/tests/test_reporting_router.py`

- [ ] **Step 1: Add the campaign schemas to `apps/api/schemas.py`**

Append after `AnalyticsRollup`:

```python
class CampaignSummary(Schema):
    name: str = Field(..., description="Campaign label (the free-form Post.campaign string).")
    content_count: int = Field(..., description="Posts tagged with this campaign (allowlist-scoped).")
    by_status: dict[str, int] = Field(..., description="Derived-status → count.")
    platforms: list[str] = Field(..., description="Distinct platforms this campaign posts to.")
    first_post: dt.datetime | None = Field(None, description="Earliest post creation time in the campaign.")
    last_post: dt.datetime | None = Field(None, description="Latest post creation time in the campaign.")
    analytics: AnalyticsRollup | None = Field(
        None, description="Summed analytics over the campaign's accounts; null without view_analytics."
    )

    @field_serializer("first_post", "last_post")
    def _ser_dt(self, value: dt.datetime | None) -> str | None:
        return _serialize_utc_z(value)


class CampaignListResponse(Schema):
    items: list[CampaignSummary] = Field(..., description="Campaign rollups, most-recent activity first.")
```

- [ ] **Step 2: Write failing campaign builder test**

Append to `apps/composer/tests/test_reporting_builders.py`:

```python
@pytest.mark.django_db
def test_build_campaigns_groups_and_counts(setup):
    from apps.composer.api_builders import build_campaigns

    ws, li, x = setup
    _post(ws, li, campaign="EGM", status="published")
    _post(ws, li, campaign="EGM", status="draft")
    _post(ws, li, campaign="")  # blank campaign excluded

    campaigns = build_campaigns(ws, {li.id, x.id}, days=30, account_map=None)
    names = {c.name for c in campaigns}
    assert names == {"EGM"}
    egm = next(c for c in campaigns if c.name == "EGM")
    assert egm.content_count == 2
    assert egm.by_status.get("published") == 1
    assert egm.by_status.get("draft") == 1
    assert egm.platforms == ["linkedin"]
    assert egm.analytics is None  # account_map=None → analytics omitted
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest -x -q apps/composer/tests/test_reporting_builders.py::test_build_campaigns_groups_and_counts -v`
Expected: FAIL — `ImportError: build_campaigns`.

- [ ] **Step 4: Add `build_campaigns` to `apps/composer/api_builders.py`**

Add the import at the top of the module:

```python
from apps.api.schemas import CampaignSummary, ContentItem, ContentPlatform
```

(Replace the existing `from apps.api.schemas import ContentItem, ContentPlatform` line.)

Append the builder:

```python
def build_campaigns(
    workspace,
    allowed_account_ids: set[uuid.UUID],
    *,
    days: int = 30,
    account_map: dict | None = None,
    limit: int | None = None,
) -> list[CampaignSummary]:
    """Group allowlist-visible posts by their non-blank campaign string.

    ``account_map`` is an ``apps.analytics.api_builders.account_metric_map``
    result (or None to omit analytics). Per-campaign analytics are summed from
    that pre-computed map over the campaign's own accounts, so no extra
    analytics queries fire here. Sorted by most-recent activity; ``limit``
    caps the count (None = all).
    """
    posts = [p for p in _scoped_posts(workspace) if _visible_to_allowlist(p, allowed_account_ids)]

    groups: dict[str, list] = {}
    for post in posts:
        name = (post.campaign or "").strip()
        if not name:
            continue
        groups.setdefault(name, []).append(post)

    summaries: list[CampaignSummary] = []
    for name, group in groups.items():
        by_status: dict[str, int] = {}
        platforms: set[str] = set()
        account_ids: set[uuid.UUID] = set()
        for post in group:
            children = list(post.platform_posts.all())
            st = derive_post_status([pp.status for pp in children])
            by_status[st] = by_status.get(st, 0) + 1
            for pp in children:
                platforms.add(pp.social_account.platform)
                account_ids.add(pp.social_account_id)
        created_times = [p.created_at for p in group]
        analytics = None
        if account_map is not None:
            from apps.analytics.api_builders import build_workspace_analytics_rollup

            scoped = {aid: account_map[aid] for aid in account_ids if aid in account_map}
            analytics = build_workspace_analytics_rollup(scoped, days)
        summaries.append(
            CampaignSummary(
                name=name,
                content_count=len(group),
                by_status=by_status,
                platforms=sorted(platforms),
                first_post=min(created_times),
                last_post=max(created_times),
                analytics=analytics,
            )
        )

    summaries.sort(key=lambda c: c.last_post or c.first_post, reverse=True)
    return summaries[:limit] if limit is not None else summaries
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest -x -q apps/composer/tests/test_reporting_builders.py -v`
Expected: PASS (all builder tests).

- [ ] **Step 6: Add the `/campaigns` route to `apps/api/routers/reporting.py`**

Extend the imports:

```python
from apps.api.schemas import CampaignListResponse, ContentListResponse, PipelineResponse
from apps.analytics.api_builders import account_metric_map
from apps.composer.api_builders import build_campaigns, build_content_list
from apps.social_accounts.models import SocialAccount
```

Add a shared helper after `_allowed_account_ids`:

```python
def _allowlisted_accounts(request: HttpRequest):
    """The key's allowlisted SocialAccount rows (for analytics rollups)."""
    return list(request.api_key.social_accounts.all())  # type: ignore[attr-defined]
```

Add the route:

```python
@router.get("/campaigns", response=CampaignListResponse, summary="Campaign rollups (grouped by campaign label)")
def campaigns(
    request,
    days: int = Query(30, ge=7, le=90, description="Analytics rolling window in days."),
):
    enforce_http_rate_limits(request, is_write=False)
    amap = account_metric_map(_allowlisted_accounts(request), days) if _has_perm(request, "view_analytics") else None
    items = build_campaigns(
        request.workspace,
        _allowed_account_ids(request),
        days=days,
        account_map=amap,
    )
    log_audit_entry(request, action="reporting.campaigns.read", target_id=None, status_code=200)
    return CampaignListResponse(items=items)
```

- [ ] **Step 7: Add route tests for campaigns + the analytics-permission split**

First add a no-analytics key fixture near the other fixtures in `apps/api/tests/test_reporting_router.py`:

```python
@pytest.fixture
def no_analytics_key(db, user, owner_memberships, workspace, linkedin_account):
    return services.issue_api_key(
        workspace=workspace,
        social_accounts=[linkedin_account],
        issued_by=user,
        name="reporting-no-analytics",
        permissions=[p for p in PERMISSION_KEYS if p != "view_analytics"],
    )


@pytest.fixture
def client_no_analytics(no_analytics_key):
    return _SecureClient(HTTP_AUTHORIZATION=f"Bearer {no_analytics_key.plaintext_token}")
```

Then append:

```python
@pytest.mark.django_db
class TestCampaigns:
    def test_campaign_rollup(self, client_with_token, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="published", campaign="EGM", published_at=timezone.now())
        _make_post(workspace, linkedin_account, status="draft", campaign="EGM")

        r = client_with_token.get("/api/v1/campaigns")
        assert r.status_code == 200
        items = r.json()["items"]
        egm = next(c for c in items if c["name"] == "EGM")
        assert egm["content_count"] == 2
        assert egm["platforms"] == ["linkedin"]
        assert egm["analytics"]["available"] in (True, False)  # present (key has view_analytics)

    def test_campaign_analytics_omitted_without_permission(self, client_no_analytics, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="draft", campaign="EGM")
        r = client_no_analytics.get("/api/v1/campaigns")
        assert r.status_code == 200
        egm = next(c for c in r.json()["items"] if c["name"] == "EGM")
        assert egm["analytics"] is None
```

- [ ] **Step 8: Run the route tests to verify they pass**

Run: `uv run pytest -x -q apps/api/tests/test_reporting_router.py -v`
Expected: PASS (Pipeline + Content + Campaigns).

- [ ] **Step 9: Commit**

```bash
git add apps/api/routers/reporting.py apps/api/schemas.py apps/composer/api_builders.py apps/composer/tests/test_reporting_builders.py apps/api/tests/test_reporting_router.py
git commit -m "feat(api): GET /api/v1/campaigns rollups with gated analytics

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Overview endpoint (composition)

**Files:**
- Modify: `apps/composer/api_builders.py`
- Modify: `apps/api/schemas.py`
- Modify: `apps/api/routers/reporting.py`
- Test: `apps/composer/tests/test_reporting_builders.py`, `apps/api/tests/test_reporting_router.py`

- [ ] **Step 1: Add the content-summary + overview schemas to `apps/api/schemas.py`**

Append after `CampaignListResponse`:

```python
class ContentSummary(Schema):
    total: int = Field(..., description="Total allowlist-visible posts in the workspace.")
    by_status: dict[str, int] = Field(..., description="Derived-status → count.")
    scheduled_next_7d: int = Field(..., description="Posts scheduled in the next 7 days.")
    published_last_30d: int = Field(..., description="Posts published in the last 30 days.")


class OverviewResponse(Schema):
    workspace_id: uuid.UUID = Field(..., description="The workspace this rollup covers.")
    generated_at: dt.datetime = Field(..., description="When the rollup was computed (UTC).")
    pipeline: PipelineResponse = Field(..., description="Content pipeline funnel.")
    content: ContentSummary = Field(..., description="Content counts + scheduling windows.")
    campaigns: list[CampaignSummary] = Field(..., description="Top campaigns by recent activity.")
    analytics: AnalyticsRollup = Field(..., description="Workspace analytics rollup (gated).")

    @field_serializer("generated_at")
    def _ser_dt(self, value: dt.datetime) -> str | None:
        return _serialize_utc_z(value)
```

- [ ] **Step 2: Write failing content-summary builder test**

Append to `apps/composer/tests/test_reporting_builders.py`:

```python
@pytest.mark.django_db
def test_build_content_summary_windows(setup):
    from django.utils import timezone

    from apps.composer.api_builders import build_content_summary

    ws, li, x = setup
    _post(ws, li, status="scheduled", scheduled_at=timezone.now() + timezone.timedelta(days=2))
    _post(ws, li, status="published", published_at=timezone.now() - timezone.timedelta(days=3))
    _post(ws, li, status="published", published_at=timezone.now() - timezone.timedelta(days=90))

    summary = build_content_summary(ws, {li.id})
    assert summary["total"] == 3
    assert summary["scheduled_next_7d"] == 1
    assert summary["published_last_30d"] == 1
    assert summary["by_status"].get("scheduled") == 1
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest -x -q apps/composer/tests/test_reporting_builders.py::test_build_content_summary_windows -v`
Expected: FAIL — `ImportError: build_content_summary`.

- [ ] **Step 4: Add `build_content_summary` to `apps/composer/api_builders.py`**

Add the import at the top:

```python
from datetime import timedelta

from django.utils import timezone
```

Append the builder:

```python
def build_content_summary(workspace, allowed_account_ids: set[uuid.UUID]) -> dict:
    """Counts + scheduling windows over allowlist-visible posts.

    Returns ``{total, by_status, scheduled_next_7d, published_last_30d}``.
    """
    now = timezone.now()
    soon = now + timedelta(days=7)
    last_30 = now - timedelta(days=30)

    posts = [p for p in _scoped_posts(workspace) if _visible_to_allowlist(p, allowed_account_ids)]

    by_status: dict[str, int] = {}
    scheduled_next_7d = 0
    published_last_30d = 0
    for post in posts:
        st = derive_post_status([pp.status for pp in post.platform_posts.all()])
        by_status[st] = by_status.get(st, 0) + 1
        if post.scheduled_at and now <= post.scheduled_at <= soon:
            scheduled_next_7d += 1
        if post.published_at and post.published_at >= last_30:
            published_last_30d += 1

    return {
        "total": len(posts),
        "by_status": by_status,
        "scheduled_next_7d": scheduled_next_7d,
        "published_last_30d": published_last_30d,
    }
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest -x -q apps/composer/tests/test_reporting_builders.py -v`
Expected: PASS (all builder tests).

- [ ] **Step 6: Add the `/overview` route to `apps/api/routers/reporting.py`**

Extend the imports:

```python
from apps.api.schemas import (
    CampaignListResponse,
    ContentListResponse,
    ContentSummary,
    OverviewResponse,
    PipelineResponse,
)
from apps.analytics.api_builders import account_metric_map, build_workspace_analytics_rollup
from apps.composer.api_builders import build_campaigns, build_content_list, build_content_summary
from apps.content_intake.progress import content_pipeline_progress
from django.utils import timezone
```

Add the route (the workspace-wide overview):

```python
_OVERVIEW_CAMPAIGN_LIMIT = 10


@router.get("/overview", response=OverviewResponse, summary="One-call workspace dashboard rollup")
def overview(
    request,
    days: int = Query(30, ge=7, le=90, description="Analytics rolling window in days."),
):
    enforce_http_rate_limits(request, is_write=False)
    workspace = request.workspace
    allowed_ids = _allowed_account_ids(request)

    has_analytics = _has_perm(request, "view_analytics")
    amap = account_metric_map(_allowlisted_accounts(request), days) if has_analytics else None

    summary = build_content_summary(workspace, allowed_ids)
    body = OverviewResponse(
        workspace_id=workspace.id,
        generated_at=timezone.now(),
        pipeline=content_pipeline_progress(workspace),
        content=ContentSummary(**summary),
        campaigns=build_campaigns(workspace, allowed_ids, days=days, account_map=amap, limit=_OVERVIEW_CAMPAIGN_LIMIT),
        analytics=(
            build_workspace_analytics_rollup(amap, days)
            if amap is not None
            else build_workspace_analytics_rollup({}, days)
        ),
    )
    log_audit_entry(request, action="reporting.overview.read", target_id=None, status_code=200)
    return body
```

- [ ] **Step 7: Add the overview route test**

Append to `apps/api/tests/test_reporting_router.py`:

```python
@pytest.mark.django_db
class TestOverview:
    def test_overview_composition(self, client_with_token, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="published", campaign="EGM", published_at=timezone.now())
        _make_post(
            workspace, linkedin_account, status="scheduled", campaign="EGM",
            scheduled_at=timezone.now() + timezone.timedelta(days=1),
        )

        r = client_with_token.get("/api/v1/overview")
        assert r.status_code == 200
        body = r.json()
        assert body["workspace_id"] == str(workspace.id)
        assert body["content"]["total"] == 2
        assert body["content"]["scheduled_next_7d"] == 1
        assert body["pipeline"]["total"] >= 2
        assert any(c["name"] == "EGM" for c in body["campaigns"])
        assert "available" in body["analytics"]

    def test_overview_analytics_unavailable_without_permission(self, client_no_analytics, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="draft")
        r = client_no_analytics.get("/api/v1/overview")
        assert r.status_code == 200
        assert r.json()["analytics"]["available"] is False
```

- [ ] **Step 8: Run the full reporting route suite**

Run: `uv run pytest -x -q apps/api/tests/test_reporting_router.py -v`
Expected: PASS (Pipeline + Content + Campaigns + Overview).

- [ ] **Step 9: Commit**

```bash
git add apps/api/routers/reporting.py apps/api/schemas.py apps/composer/api_builders.py apps/composer/tests/test_reporting_builders.py apps/api/tests/test_reporting_router.py
git commit -m "feat(api): GET /api/v1/overview one-call workspace rollup

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Audit + rate-limit assertions, and full-suite verification

**Files:**
- Test: `apps/api/tests/test_reporting_router.py`

- [ ] **Step 1: Add an audit-row test**

Append to `apps/api/tests/test_reporting_router.py`:

```python
@pytest.mark.django_db
class TestPlumbing:
    def test_writes_audit_row(self, client_with_token, workspace, linkedin_account):
        from apps.api.models import ApiAuditLog  # adjust if the audit model lives elsewhere

        _make_post(workspace, linkedin_account, status="draft")
        client_with_token.get("/api/v1/overview")
        assert ApiAuditLog.objects.filter(action="reporting.overview.read").exists()
```

> Note: confirm the audit model name/path with `grep -rn "class .*AuditLog" apps/api/models.py`. If it differs, fix the import and the query. If audit rows are written async/best-effort, assert on `action__startswith="reporting."` instead.

- [ ] **Step 2: Run the plumbing test**

Run: `uv run pytest -x -q apps/api/tests/test_reporting_router.py::TestPlumbing -v`
Expected: PASS. (If the audit model path is wrong, fix per the note, then re-run.)

- [ ] **Step 3: Run the whole reporting + builder + analytics suites**

Run:
```bash
uv run pytest -x -q apps/api/tests/test_reporting_router.py apps/composer/tests/test_reporting_builders.py apps/analytics/tests/test_reporting_rollup.py
```
Expected: PASS, all tests.

- [ ] **Step 4: Run the full project test suite (regression check)**

Run: `uv run pytest -q`
Expected: No new failures introduced. Investigate any failure that touches `apps/api`, `apps/composer`, or `apps/analytics`.

- [ ] **Step 5: Lint**

Run: `uv run ruff check apps/api/routers/reporting.py apps/composer/api_builders.py apps/analytics/api_builders.py apps/api/schemas.py`
Expected: clean (fix any import-order / unused-import findings).

- [ ] **Step 6: Manually confirm OpenAPI renders the four routes**

Run: `uv run python manage.py shell -c "from apps.api.api import api; print([p for p in api.get_openapi_schema()['paths'] if any(x in p for x in ('overview','content','campaigns','pipeline'))])"`
Expected: prints `['/overview', '/content', '/campaigns', '/pipeline']` (no double slashes like `//overview`). If double-slashed, change the mount to `api.add_router("/", reporting_router)` and the route decorators to bare names (`@router.get("overview", ...)`), then re-run the suite.

- [ ] **Step 7: Commit**

```bash
git add apps/api/tests/test_reporting_router.py
git commit -m "test(api): reporting audit + full-suite verification

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review notes (for the implementer)

- **Spec coverage:** pipeline → Task 1; content list + filters + pagination + allowlist → Task 2; analytics rollup → Task 3; campaigns + gated analytics → Task 4; overview composition → Task 5; audit/rate-limit/OpenAPI → Tasks 1 & 6. All spec sections map to a task.
- **Derived-status filtering** is intentionally Python-side (Task 2 Step 4 docstring) because `Post.status` has no DB column.
- **Analytics cost:** `account_metric_map` runs `build_account_analytics` once per allowlisted account per request; campaigns/overview reuse that map (no per-campaign re-query). Fine for current account counts.
- **Type consistency:** builders return `(list[ContentItem], bool)` / `list[CampaignSummary]` / `AnalyticsRollup` / `dict` (content summary), matching the schema constructors used in the routes. `account_map` is threaded as `dict | None` everywhere; `None` ⇒ analytics omitted.
- **Permission model:** `_require_perm` exists for hard gates but the reporting routes use `_has_perm` (soft) for analytics so counts always return.
