# Ghost (Nexus Brief) Publish Channel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add Ghost CMS (`the-nexus-brief.ghost.io`) as a first-class publish channel — connect once at org level via an Admin API key, then compose/schedule/publish human-authored content as a web **Post** or email-only **Newsletter**, gated like every other channel.

**Architecture:** Reuse the existing provider pattern. A `GhostProvider(SocialProvider)` signs a per-request Ghost Admin JWT (stdlib HMAC) and calls the Ghost Admin API. Credentials live in the org-scoped `PlatformCredential` (resolved automatically by `engine._resolve_publish_credentials`). One shared `SocialAccount(platform="ghost")` is surfaced to every workspace's composer. The publish-as choice rides the existing `PlatformPost.platform_extra` mechanism.

**Tech Stack:** Django 5, httpx, Python stdlib (`hmac`/`hashlib`/`base64`/`json`/`time`), pytest-django.

**Conventions:** Run tests with `cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform && export PATH="$HOME/.local/bin:$PATH" && uv run python -m pytest <paths> -q`. No live network in unit tests (mock `httpx`). Spec: `docs/superpowers/specs/2026-06-11-ghost-nexus-channel-design.md`.

---

### Task 1: Platform enum + `AuthType.API_KEY` + char limit

**Files:** Modify `providers/types.py`, `apps/credentials/models.py`, `apps/social_accounts/models.py`; Test `tests/test_ghost_platform_enum.py`

- [ ] **Step 1: Failing test** — create `tests/test_ghost_platform_enum.py`:
```python
def test_ghost_platform_registered():
    from apps.credentials.models import PlatformCredential
    assert PlatformCredential.Platform.GHOST == "ghost"

def test_api_key_auth_type_exists():
    from providers.types import AuthType
    assert AuthType.API_KEY.value == "api_key"

def test_ghost_char_limit_present():
    from apps.social_accounts.models import SocialAccount
    assert SocialAccount.PLATFORM_CHAR_LIMITS.get("ghost", 0) >= 50000
```
- [ ] **Step 2: Run → FAIL** (`AttributeError`). `uv run python -m pytest tests/test_ghost_platform_enum.py -q`
- [ ] **Step 3: Implement**
  - `providers/types.py` `AuthType` enum: add `API_KEY = "api_key"`.
  - `apps/credentials/models.py` `PlatformCredential.Platform`: add `GHOST = "ghost", "Ghost (Nexus Brief)"`.
  - `apps/social_accounts/models.py`: in `PLATFORM_CHAR_LIMITS` add `"ghost": 100000,`.
  - Adding a `TextChoices` value does **not** alter the DB column → **no migration needed**.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(ghost): register ghost platform + API_KEY auth type + char limit"`

---

### Task 2: Ghost Admin JWT (stdlib)

**Files:** Create `providers/ghost_jwt.py`; Test `tests/test_ghost_jwt.py`

- [ ] **Step 1: Failing test** — `tests/test_ghost_jwt.py`:
```python
import base64, hashlib, hmac, json

def _b64url_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def test_jwt_structure_and_signature():
    from providers.ghost_jwt import ghost_admin_jwt
    key_id = "1111111111111111111111aa"
    secret_hex = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    token = ghost_admin_jwt(f"{key_id}:{secret_hex}")
    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(_b64url_decode(header_b64))
    payload = json.loads(_b64url_decode(payload_b64))
    assert header == {"alg": "HS256", "typ": "JWT", "kid": key_id}
    assert payload["aud"] == "/admin/"
    assert payload["exp"] - payload["iat"] == 300
    expected = hmac.new(bytes.fromhex(secret_hex),
                        f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    assert _b64url_decode(sig_b64) == expected

def test_jwt_rejects_malformed_key():
    import pytest
    from providers.ghost_jwt import ghost_admin_jwt
    with pytest.raises(ValueError):
        ghost_admin_jwt("no-colon-here")
```
- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError`).
- [ ] **Step 3: Implement `providers/ghost_jwt.py`:**
```python
"""Ghost Admin API JWT signing (stdlib only — no external dependency).

Ghost Admin auth: HS256 JWT with the key id in the header ``kid``, a 5-minute
expiry, aud="/admin/", signed with the secret decoded from hex to bytes.
Mirrors docs/ghost.md §3. Generate fresh per request — tokens expire in 5 min.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def ghost_admin_jwt(admin_api_key: str) -> str:
    """Return a signed Ghost Admin API JWT for ``<key_id>:<hex_secret>``."""
    if ":" not in admin_api_key:
        raise ValueError("Ghost Admin API key must be in '<id>:<secret>' form")
    key_id, secret_hex = admin_api_key.split(":", 1)
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT", "kid": key_id}).encode())
    now = int(time.time())
    payload = _b64url(json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(bytes.fromhex(secret_hex), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(signature)}"
```
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add providers/ghost_jwt.py tests/test_ghost_jwt.py && git commit -m "feat(ghost): stdlib Ghost Admin JWT signing"`

---

### Task 3: `GhostProvider` — connect/profile + Post-mode publish

**Files:** Create `providers/ghost.py`; Test `tests/test_ghost_provider.py`

- [ ] **Step 1: Failing test** — `tests/test_ghost_provider.py`:
```python
import httpx
from providers.ghost import GhostProvider
from providers.types import AuthType, PublishContent

CREDS = {"admin_api_key": "id123:" + "ab" * 32, "base_url": "https://demo.ghost.io"}

def _provider():
    return GhostProvider(credentials=dict(CREDS))

def test_auth_type_is_api_key():
    assert _provider().auth_type == AuthType.API_KEY

def test_publish_as_post_hits_posts_endpoint(monkeypatch):
    captured = {}
    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url; captured["json"] = json; captured["headers"] = headers
        return httpx.Response(201, json={"posts": [{"id": "p1", "url": "https://demo.ghost.io/p1/"}]})
    monkeypatch.setattr("providers.ghost.httpx.post", fake_post)
    res = _provider().publish_post("unused", PublishContent(text="Hello body",
        extra={"title": "My Brief", "ghost_publish_as": "post"}))
    assert res.platform_post_id == "p1"
    assert "/ghost/api/admin/posts/?source=html" in captured["url"]
    assert "newsletter=" not in captured["url"]
    assert captured["json"]["posts"][0]["title"] == "My Brief"
    assert captured["headers"]["Authorization"].startswith("Ghost ")

def test_get_profile_validates_key(monkeypatch):
    monkeypatch.setattr("providers.ghost.httpx.get",
        lambda url, headers=None, **kw: httpx.Response(200, json={"site": {"title": "Nexus Brief", "url": "https://demo.ghost.io"}}))
    prof = _provider().get_profile("unused")
    assert prof.name == "Nexus Brief"
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement `providers/ghost.py`** (model the property shape on `providers/mock.py`):
```python
"""Ghost (Nexus Brief) provider — publish to a Ghost site via the Admin API.

Auth is a single Admin API key (no per-user OAuth); a fresh JWT is signed per
request. Publishes human-authored content as a web Post (default) or an
email-only Newsletter (``extra['ghost_publish_as'] == 'newsletter'``).
"""
from __future__ import annotations

import html as _html

import httpx

from .base import SocialProvider
from .exceptions import PublishError
from .ghost_jwt import ghost_admin_jwt
from .types import (
    AccountProfile, AuthType, MediaType, PostType, PublishContent, PublishResult,
)

_TIMEOUT = 20.0
_HEADERS_VERSION = "v5.0"


class GhostProvider(SocialProvider):
    @property
    def platform_name(self) -> str:
        return "Ghost (Nexus Brief)"

    @property
    def auth_type(self) -> AuthType:
        return AuthType.API_KEY

    @property
    def max_caption_length(self) -> int:
        return 100000

    @property
    def supported_post_types(self) -> list[PostType]:
        return [PostType.TEXT, PostType.ARTICLE]

    @property
    def supported_media_types(self) -> list[MediaType]:
        return [MediaType.JPEG, MediaType.PNG]

    @property
    def required_scopes(self) -> list[str]:
        return []

    # -- helpers -------------------------------------------------------
    def _key(self) -> str:
        key = self.credentials.get("admin_api_key")
        if not key:
            raise PublishError("Ghost admin_api_key not configured")
        return key

    def _base(self) -> str:
        base = (self.credentials.get("base_url") or "").rstrip("/")
        if not base:
            raise PublishError("Ghost base_url not configured")
        return base

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Ghost {ghost_admin_jwt(self._key())}",
            "Content-Type": "application/json",
            "Accept-Version": _HEADERS_VERSION,
        }

    @staticmethod
    def _to_html(text: str) -> str:
        paras = [p for p in (text or "").split("\n") if p.strip()]
        return "".join(f"<p>{_html.escape(p)}</p>" for p in paras) or "<p></p>"

    # -- profile (connect validation) ----------------------------------
    def get_profile(self, access_token: str) -> AccountProfile:
        resp = httpx.get(f"{self._base()}/ghost/api/admin/site/",
                         headers=self._auth_headers(), timeout=_TIMEOUT)
        if resp.status_code != 200:
            raise PublishError(f"Ghost validation failed ({resp.status_code}): {resp.text[:200]}")
        site = resp.json().get("site", {})
        return AccountProfile(platform_id=site.get("url", self._base()),
                              name=site.get("title", "Ghost"), handle=None)

    # -- publish -------------------------------------------------------
    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        title = (content.extra.get("title") or (content.text or "").split("\n", 1)[0] or "Untitled")[:255]
        excerpt = (content.text or "").strip()[:280]
        post_obj = {"title": title, "html": self._to_html(content.text),
                    "custom_excerpt": excerpt, "status": "published",
                    "tags": [{"name": "AfCEN"}]}
        mode = content.extra.get("ghost_publish_as", "post")
        url = f"{self._base()}/ghost/api/admin/posts/?source=html"
        if mode == "newsletter":
            slug = self.credentials.get("newsletter_slug")
            if not slug:
                raise PublishError("Newsletter publish needs a configured newsletter_slug")
            url = f"{self._base()}/ghost/api/admin/posts/?newsletter={slug}&source=html"
            post_obj["email_only"] = True
        resp = httpx.post(url, headers=self._auth_headers(),
                          json={"posts": [post_obj]}, timeout=_TIMEOUT)
        if resp.status_code not in (200, 201):
            raise PublishError(f"Ghost publish failed ({resp.status_code}): {resp.text[:300]}")
        post = resp.json().get("posts", [{}])[0]
        return PublishResult(platform_post_id=post.get("id", ""), url=post.get("url"),
                             extra={"ghost_publish_as": mode})
```
> If `providers/exceptions.py` lacks `PublishError`, use the publish exception it does define (check `grep -n "class .*Error" providers/exceptions.py`) and adjust the import + the test's expected exception accordingly.
- [ ] **Step 4: Run → PASS.** `uv run python -m pytest tests/test_ghost_provider.py -q`
- [ ] **Step 5: Commit** `git add providers/ghost.py tests/test_ghost_provider.py && git commit -m "feat(ghost): GhostProvider — connect + post-mode publish"`

---

### Task 4: `GhostProvider` — Newsletter (email-only) mode

**Files:** Modify `tests/test_ghost_provider.py` (provider already supports it from Task 3)

- [ ] **Step 1: Add failing tests** to `tests/test_ghost_provider.py`:
```python
def test_newsletter_mode_email_only(monkeypatch):
    captured = {}
    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url; captured["json"] = json
        return httpx.Response(201, json={"posts": [{"id": "n1", "url": "https://demo.ghost.io/n1/"}]})
    monkeypatch.setattr("providers.ghost.httpx.post", fake_post)
    creds = dict(CREDS); creds["newsletter_slug"] = "weekly"
    res = GhostProvider(credentials=creds).publish_post("x",
        PublishContent(text="Body", extra={"title": "T", "ghost_publish_as": "newsletter"}))
    assert res.platform_post_id == "n1"
    assert "newsletter=weekly" in captured["url"]
    assert captured["json"]["posts"][0]["email_only"] is True

def test_newsletter_without_slug_fails():
    import pytest
    from providers.exceptions import PublishError  # adjust if name differs
    with pytest.raises(PublishError):
        GhostProvider(credentials=dict(CREDS)).publish_post("x",
            PublishContent(text="B", extra={"ghost_publish_as": "newsletter"}))
```
- [ ] **Step 2: Run → PASS** (implemented in Task 3). If the no-slug test errors with a different exception class, fix the import to match `providers/exceptions.py`.
- [ ] **Step 3: Commit** `git add tests/test_ghost_provider.py && git commit -m "test(ghost): newsletter email-only mode + missing-slug failure"`

---

### Task 5: Register provider + env fallback

**Files:** Modify `providers/__init__.py`, `config/settings/base.py`, `.env.example`; Test `tests/test_ghost_registry.py`

- [ ] **Step 1: Failing test** — `tests/test_ghost_registry.py`:
```python
def test_get_provider_returns_ghost():
    from providers import get_provider
    from providers.ghost import GhostProvider
    p = get_provider("ghost", {"admin_api_key": "a:bb", "base_url": "https://x.ghost.io"})
    assert isinstance(p, GhostProvider)
```
- [ ] **Step 2: Run → FAIL** (`No provider registered`).
- [ ] **Step 3: Implement**
  - `providers/__init__.py`: `from .ghost import GhostProvider` and add `"ghost": GhostProvider,` to `PROVIDER_REGISTRY`.
  - `config/settings/base.py`: in the `PLATFORM_CREDENTIALS_FROM_ENV` builder add a `ghost` entry from env (mirror existing platforms):
    ```python
    # near the other PLATFORM_CREDENTIALS_FROM_ENV entries
    if env("GHOST_ADMIN_API_KEY", default=""):
        PLATFORM_CREDENTIALS_FROM_ENV["ghost"] = {
            "admin_api_key": env("GHOST_ADMIN_API_KEY"),
            "base_url": env("GHOST_BASE_URL", default="https://the-nexus-brief.ghost.io"),
            "newsletter_slug": env("GHOST_NEWSLETTER_SLUG", default=""),
        }
    ```
    (Match the exact construction style already used in `base.py` for `PLATFORM_CREDENTIALS_FROM_ENV` — read it first; if it's a literal dict, add the `ghost` key conditionally after it.)
  - `.env.example`: append `GHOST_ADMIN_API_KEY=`, `GHOST_BASE_URL=https://the-nexus-brief.ghost.io`, `GHOST_NEWSLETTER_SLUG=`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(ghost): register provider + env credential fallback"`

---

### Task 6: Credentials form fields (optional newsletter_slug)

**Files:** Modify `apps/credentials/platform_fields.py`, `apps/credentials/views.py`; Test `tests/test_ghost_credentials.py`

- [ ] **Step 1: Failing test** — `tests/test_ghost_credentials.py`:
```python
def test_ghost_fields_declared():
    from apps.credentials.platform_fields import PLATFORM_FIELDS, required_field_keys
    assert "ghost" in PLATFORM_FIELDS
    req = required_field_keys("ghost")
    assert "admin_api_key" in req and "base_url" in req
    assert "newsletter_slug" not in req  # optional
```
- [ ] **Step 2: Run → FAIL** (`required_field_keys` missing / no ghost).
- [ ] **Step 3: Implement**
  - `apps/credentials/platform_fields.py`: add the ghost entry. Field tuples become `(key, label, type, required)` with `required` defaulting True for existing entries (leave them 3-tuples; treat a 3-tuple as required):
    ```python
    "ghost": {
        "label": "Ghost (Nexus Brief)",
        "help": "Ghost Admin → Settings → Integrations → Custom integration. "
                "Paste the Admin API Key (id:secret) and your site URL.",
        "fields": [
            ("admin_api_key", "Admin API Key (id:secret)", "password"),
            ("base_url", "Site URL (https://your.ghost.io)", "text"),
            ("newsletter_slug", "Newsletter slug (optional, for email sends)", "text", False),
        ],
    },
    ```
  - Add a helper and use it in `save_credential`'s `is_configured`:
    ```python
    def required_field_keys(platform: str) -> list[str]:
        spec = PLATFORM_FIELDS.get(platform, {})
        return [f[0] for f in spec.get("fields", []) if len(f) < 4 or f[3]]
    ```
  - `apps/credentials/views.py` `save_credential`: change `is_configured = all(creds.get(k) for k in keys)` → `is_configured = all(creds.get(k) for k in required_field_keys(platform))` (import `required_field_keys`). Keep saving optional fields when present (the existing `for key in keys` loop already does).
- [ ] **Step 4: Run → PASS.** Also run `uv run python -m pytest apps/credentials -q` (no regressions).
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(ghost): credentials fields w/ optional newsletter_slug"`

---

### Task 7: Connect Ghost → one org-level SocialAccount

**Files:** Modify `apps/credentials/views.py`, `apps/credentials/urls.py`, `templates/credentials/list.html`; Test `tests/test_ghost_connect.py`

- [ ] **Step 1: Failing test** — `tests/test_ghost_connect.py`:
```python
import pytest
from django.urls import reverse

@pytest.mark.django_db
def test_connect_ghost_creates_single_account(client, org_owner, organization, monkeypatch):
    from apps.credentials.models import PlatformCredential
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    from providers.types import AccountProfile
    Workspace.objects.create(name="Main", organization=organization)
    PlatformCredential.objects.create(organization=organization, platform="ghost",
        credentials={"admin_api_key": "a:bb", "base_url": "https://demo.ghost.io"}, is_configured=True)
    monkeypatch.setattr("providers.ghost.GhostProvider.get_profile",
        lambda self, t="": AccountProfile(platform_id="demo.ghost.io", name="Nexus Brief"))
    client.force_login(org_owner)
    resp = client.post(reverse("credentials:connect-ghost"))
    assert resp.status_code in (302, 200)
    qs = SocialAccount.objects.filter(platform="ghost", workspace__organization=organization)
    assert qs.count() == 1
    assert qs.first().account_name == "Nexus Brief"
    # idempotent
    client.post(reverse("credentials:connect-ghost"))
    assert qs.count() == 1
```
> Uses the `org_owner`/`organization` fixtures already in root `conftest.py`.
- [ ] **Step 2: Run → FAIL** (no url `credentials:connect-ghost`).
- [ ] **Step 3: Implement**
  - `apps/credentials/views.py` add:
    ```python
    @login_required
    def connect_ghost(request):
        org = _get_org(request)
        if not _can_manage(request, org):
            messages.error(request, "You need org owner/admin to connect channels.")
            return redirect("credentials:list")
        cred = PlatformCredential.objects.for_org(org.id).filter(platform="ghost", is_configured=True).first()
        if not cred:
            messages.error(request, "Save Ghost credentials first.")
            return redirect("credentials:list")
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.models import Workspace
        from providers import get_provider
        try:
            profile = get_provider("ghost", dict(cred.credentials)).get_profile("")
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Ghost connection failed: {exc}")
            return redirect("credentials:list")
        ws = Workspace.objects.filter(organization=org).order_by("created_at").first()
        if ws is None:
            messages.error(request, "Create a workspace first.")
            return redirect("credentials:list")
        SocialAccount.objects.update_or_create(
            workspace=ws, platform="ghost", account_platform_id=profile.platform_id,
            defaults={"account_name": profile.name,
                      "connection_status": SocialAccount.ConnectionStatus.CONNECTED},
        )
        messages.success(request, f"Connected Ghost: {profile.name}.")
        return redirect("credentials:list")
    ```
    (If `Workspace` has no `created_at`, order by `id`.)
  - `apps/credentials/urls.py`: add `path("connect/ghost/", views.connect_ghost, name="connect-ghost")`.
  - `templates/credentials/list.html`: in the Ghost row, add a "Connect" button POSTing to `{% url 'credentials:connect-ghost' %}` (with `{% csrf_token %}`), shown once Ghost is configured — mirror the existing per-platform action markup.
- [ ] **Step 4: Run → PASS.** `uv run python -m pytest tests/test_ghost_connect.py -q`
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(ghost): connect → single org-level Ghost SocialAccount"`

---

### Task 8: Engine — inject title + publish-as for Ghost

**Files:** Modify `apps/publisher/engine.py`; Test `apps/publisher/tests/test_ghost_dispatch.py`

- [ ] **Step 1: Failing test** — `apps/publisher/tests/test_ghost_dispatch.py`:
```python
import pytest

@pytest.mark.django_db
def test_ghost_extra_carries_title_and_publish_as(due_platform_post_factory, monkeypatch):
    pp = due_platform_post_factory(platform="ghost")
    pp.platform_extra = {"ghost_publish_as": "newsletter"}; pp.save()
    pp.post.title = "Weekly Brief"; pp.post.save()
    captured = {}
    from providers.types import PublishResult
    class FakeProvider:
        auth_type = __import__("providers.types", fromlist=["AuthType"]).AuthType.API_KEY
        supported_post_types = []
        def publish_post(self, token, content):
            captured["extra"] = content.extra; return PublishResult(platform_post_id="g1")
    monkeypatch.setattr("apps.publisher.engine.get_provider", lambda *a, **k: FakeProvider())
    from apps.publisher.engine import PublishEngine
    PublishEngine().poll_and_publish()
    assert captured["extra"].get("title") == "Weekly Brief"
    assert captured["extra"].get("ghost_publish_as") == "newsletter"
```
> The `due_platform_post_factory` fixture (root `conftest.py`) accepts `platform=`. The gate must pass for a `mock`/test platform — if the gate blocks `ghost` in tests, set `gate_id`/`content_hash` per the fixture so `_gate_failure_reason` returns None, mirroring `test_joseph_gate.py`.
- [ ] **Step 2: Run → FAIL** (title/publish_as absent from extra).
- [ ] **Step 3: Implement** — in `apps/publisher/engine.py`, in the block that builds `extra` (right after the Facebook `page_id` / LinkedIn `author` injections, ~line 525-530), add:
```python
            # Ghost: title comes from the Post; default web-post mode.
            if platform == "ghost":
                extra.setdefault("title", platform_post.post.title or "")
                extra.setdefault("ghost_publish_as", (platform_post.platform_extra or {}).get("ghost_publish_as", "post"))
```
- [ ] **Step 4: Run → PASS.** Also `uv run python -m pytest apps/publisher -q`.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(ghost): thread title + publish-as through the publish engine"`

---

### Task 9: Composer — surface org Ghost account + Post/Newsletter toggle

**Files:** Modify `apps/composer/views.py`, the compose template (the channel picker + per-channel options); Test `apps/composer/tests/test_ghost_compose.py`

- [ ] **Step 1: Failing test** — `apps/composer/tests/test_ghost_compose.py`:
```python
import pytest

@pytest.mark.django_db
def test_org_ghost_account_visible_in_other_workspace(client, org_owner, organization):
    from apps.workspaces.models import Workspace
    from apps.social_accounts.models import SocialAccount
    from apps.composer.views import available_accounts_for  # helper added below
    w1 = Workspace.objects.create(name="House A", organization=organization)
    w2 = Workspace.objects.create(name="House B", organization=organization)
    SocialAccount.objects.create(workspace=w1, platform="ghost",
        account_platform_id="demo.ghost.io", account_name="Nexus Brief",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED)
    ids = {a.id for a in available_accounts_for(w2)}
    ghost = SocialAccount.objects.get(platform="ghost")
    assert ghost.id in ids  # org-level ghost visible from House B
```
- [ ] **Step 2: Run → FAIL** (`available_accounts_for` missing).
- [ ] **Step 3: Implement**
  - `apps/composer/views.py`: extract the picker query (currently `SocialAccount.objects.for_workspace(workspace.id)...` at ~line 340) into a helper and union org-level ghost:
    ```python
    def available_accounts_for(workspace):
        from django.db.models import Q
        from apps.social_accounts.models import SocialAccount
        return SocialAccount.objects.filter(
            Q(workspace=workspace)
            | Q(platform="ghost", workspace__organization_id=workspace.organization_id)
        ).distinct()
    ```
    Replace the inline query at the picker site with `available_accounts_for(workspace)` (preserve any existing ordering/`.select_related`).
  - **Toggle UI:** in the compose template, when a selected channel's `platform == "ghost"`, render a "Publish as" control (radio: Post / Newsletter) whose value is saved into that channel's `platform_extra["ghost_publish_as"]`. In `save_post` (`apps/composer/views.py`, where `platform_extra` is assembled per `PlatformPost` — see the `youtube`/`pinterest` branches ~line 104-117), add a `ghost` branch:
    ```python
    if account.platform == "ghost":
        mode = request.POST.get(f"ghost_publish_as_{account.id}", "post")
        platform_extra["ghost_publish_as"] = "newsletter" if mode == "newsletter" else "post"
    ```
    (Match the exact way `platform_extra` is built/persisted in `save_post`.)
- [ ] **Step 4: Run → PASS.** Also `uv run python -m pytest apps/composer -q`.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat(ghost): org-level account in composer + Post/Newsletter toggle"`

---

### Task 10: Rotate leaked secrets in the doc

**Files:** Modify `docs/ghost.md`

- [ ] **Step 1:** Replace the live key/secret/content-key values in `docs/ghost.md` §2 with placeholders (`<KEY_ID>`, `<SECRET_HEX>`, `<CONTENT_API_KEY>`) and add a one-line note: "Live keys are stored in the encrypted credential store / env (`GHOST_ADMIN_API_KEY`). The previously-committed keys have been rotated." Keep the JWT how-to intact.
- [ ] **Step 2:** Manual action note for the operator (cannot be automated): **rotate** the Admin + Content keys in Ghost Admin → Integrations, since the originals were in git history.
- [ ] **Step 3: Commit** `git add docs/ghost.md && git commit -m "docs(ghost): redact live keys (rotated) — use env/credential store"`

---

### Task 11: Full-suite verification

**Files:** none

- [ ] **Step 1:** `cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform && export PATH="$HOME/.local/bin:$PATH" && uv run python -m pytest -q --create-db` (run **alone** — no concurrent pytest; the suite shares one test DB). Expected: all green.
- [ ] **Step 2 (post-deploy smoke, manual):** with real Ghost creds in the credential store, connect Ghost, compose a one-line draft, publish as **Post** → confirm it appears on the Ghost site; repeat as **Newsletter** with a slug → confirm the email send. Verify a gate-blocked draft does **not** publish.

---

## Notes for the executor
- Do not touch `agent-service/`.
- One Ghost connection per org (Task 7) — never create per-workspace duplicates.
- Ghost auth is API-key; the engine's OAuth token-refresh block is skipped for `AuthType.API_KEY` (no change needed).
- Run the full suite **alone** — overlapping pytest runs collide on the shared `test_brightbean_test` DB (see `reference_test_db_overlap`).
