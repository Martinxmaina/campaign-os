# Blotato Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish to Instagram, Facebook, Threads, Bluesky, and personal LinkedIn via Blotato — a new add-on provider family behind the existing compliance gate.

**Architecture:** Approach A from the spec — a `BlotatoProvider` base + thin per-target subclasses registered as `blotato_<target>` in the existing `PROVIDER_REGISTRY`. Per-account Blotato data (accountId, Facebook pageId) flows through the engine's existing `content.extra` injection seam, so the `publish_post(access_token, content)` dispatch contract is unchanged. Publishing is async: submit to `POST /v2/posts`, poll `GET /v2/posts/{id}`; on poll-timeout raise `BlotatoStillPublishing` so the engine parks the post at `publishing` and a reconcile beat task finalizes it (never re-submits → no duplicate posts).

**Tech Stack:** Django 5.1, providers/ package (httpx via `SocialProvider._request`), Celery beat, pytest-django.

**Spec:** `docs/superpowers/specs/2026-06-23-blotato-integration-design.md`

**Test command (use the isolated DB to avoid the shared-test-DB overlap):**
Create a throwaway `config/settings/test_iso.py` (NOT committed) once:
```python
from .test import *  # noqa: F401,F403
DATABASES["default"]["NAME"] = "campaign_os_iso"  # noqa: F405
DATABASES["default"].setdefault("TEST", {})["NAME"] = "test_campaign_os_iso"  # noqa: F405
```
Then run tests as:
`DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest <paths> -q -p no:warnings --no-header --reuse-db`
Delete `config/settings/test_iso.py` before the final commit.

---

### Task 1: Settings constants + `SocialAccount.provider_config` field

**Files:**
- Modify: `config/settings/base.py`
- Modify: `apps/social_accounts/models.py` (SocialAccount, after `instance_url` ~line 43)
- Create: `apps/social_accounts/migrations/0010_socialaccount_provider_config.py` (via makemigrations)
- Test: `apps/social_accounts/tests/test_provider_config.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/social_accounts/tests/test_provider_config.py
import pytest


@pytest.fixture
def workspace(db):
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    return Workspace.objects.create(organization=org, name="WAIIS")


@pytest.mark.django_db
def test_provider_config_defaults_to_empty_dict(workspace):
    from apps.social_accounts.models import SocialAccount
    acct = SocialAccount.objects.create(
        workspace=workspace, platform="blotato_instagram",
        account_platform_id="98432", account_name="AfCEN",
    )
    acct.refresh_from_db()
    assert acct.provider_config == {}
    acct.provider_config = {"blotato_account_id": "98432", "page_id": "777"}
    acct.save(update_fields=["provider_config"])
    acct.refresh_from_db()
    assert acct.provider_config["page_id"] == "777"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/social_accounts/tests/test_provider_config.py -q -p no:warnings --reuse-db`
Expected: FAIL — `TypeError`/`FieldError` (no `provider_config`).

- [ ] **Step 3: Add the field**

In `apps/social_accounts/models.py`, inside `class SocialAccount`, after the `instance_url` field add:
```python
    # Provider-specific per-account config that doesn't fit the OAuth fields.
    # Blotato uses {"blotato_account_id": "...", "page_id": "..."}; reserved for
    # future per-platform config (TikTok privacy defaults, etc.).
    provider_config = models.JSONField(default=dict, blank=True)
```

In `config/settings/base.py`, near other integration settings, add:
```python
# Blotato multi-platform publishing (add-on providers). One workspace API key;
# falls back here when no org-level PlatformCredential(platform="blotato") exists.
BLOTATO_API_KEY = env("BLOTATO_API_KEY", default="")
BLOTATO_API_BASE = env("BLOTATO_API_BASE", default="https://backend.blotato.com/v2")
BLOTATO_PUBLISH_TIMEOUT = env.int("BLOTATO_PUBLISH_TIMEOUT", default=30)  # inline poll budget (s)
BLOTATO_POLL_INTERVAL = env.int("BLOTATO_POLL_INTERVAL", default=2)  # seconds between polls
```

- [ ] **Step 4: Make + run the migration, then run the test**

Run: `/Users/macbook/.local/bin/uv run python manage.py makemigrations social_accounts`
Then: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/social_accounts/tests/test_provider_config.py -q -p no:warnings --reuse-db`
Expected: PASS (note: with `--reuse-db`, the new migration applies on first run; if it errors about a missing column, drop `test_campaign_os_iso` once and re-run).

- [ ] **Step 5: Commit**

```bash
git add apps/social_accounts/models.py apps/social_accounts/migrations/ config/settings/base.py apps/social_accounts/tests/test_provider_config.py
git commit -m "feat(social): SocialAccount.provider_config + Blotato settings"
```

---

### Task 2: `BlotatoStillPublishing` exception

**Files:**
- Modify: `providers/exceptions.py`
- Test: `providers/tests/test_blotato_exceptions.py` (create dir/file)

- [ ] **Step 1: Write the failing test**

```python
# providers/tests/test_blotato_exceptions.py
from providers.exceptions import BlotatoStillPublishing, ProviderError


def test_still_publishing_carries_submission_id():
    err = BlotatoStillPublishing("sub_123", platform="Instagram (Blotato)")
    assert isinstance(err, ProviderError)
    assert err.submission_id == "sub_123"
    assert "sub_123" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/macbook/.local/bin/uv run pytest providers/tests/test_blotato_exceptions.py -q`
Expected: FAIL — `ImportError: cannot import name 'BlotatoStillPublishing'`.

- [ ] **Step 3: Add the exception**

Append to `providers/exceptions.py`:
```python
class BlotatoStillPublishing(ProviderError):
    """Blotato accepted the post but it was still in-progress at our poll timeout.

    The engine parks the PlatformPost at ``publishing`` and persists the Blotato
    ``submission_id``; the reconcile beat task finalizes it later. We never
    re-submit (``POST /v2/posts`` is not idempotent → re-submit would duplicate).
    """

    def __init__(self, submission_id: str, **kwargs):
        self.submission_id = submission_id
        super().__init__(f"Blotato post {submission_id} still in progress", **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/macbook/.local/bin/uv run pytest providers/tests/test_blotato_exceptions.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add providers/exceptions.py providers/tests/test_blotato_exceptions.py
git commit -m "feat(providers): BlotatoStillPublishing exception"
```

---

### Task 3: `BlotatoProvider` base + per-target subclasses + registry

**Files:**
- Create: `providers/blotato.py`
- Modify: `providers/__init__.py` (registry)
- Test: `providers/tests/test_blotato_provider.py`

- [ ] **Step 1: Write the failing tests**

```python
# providers/tests/test_blotato_provider.py
from unittest.mock import MagicMock

import pytest

from providers import get_provider
from providers.blotato import BlotatoFacebookProvider, BlotatoInstagramProvider
from providers.exceptions import BlotatoStillPublishing, PublishError
from providers.types import PublishContent


def _resp(json_data, text="", status=200):
    r = MagicMock()
    r.json.return_value = json_data
    r.text = text
    r.status_code = status
    return r


def _content(text="hi", extra=None, media_urls=None):
    return PublishContent(text=text, media_urls=media_urls or [], extra=extra or {})


def test_registry_exposes_blotato_targets():
    assert isinstance(get_provider("blotato_instagram", {"api_key": "k"}), BlotatoInstagramProvider)
    assert get_provider("blotato_instagram", {"api_key": "k"}).target_type == "instagram"
    assert get_provider("blotato_facebook", {"api_key": "k"}).target_type == "facebook"


def test_publish_submits_then_returns_published(monkeypatch):
    p = BlotatoInstagramProvider({"api_key": "k"})
    calls = []

    def fake_request(method, url, **kw):
        calls.append((method, url, kw))
        if url.endswith("/posts"):
            # assert payload shape
            body = kw["json"]["post"]
            assert body["accountId"] == "98432"
            assert body["content"]["platform"] == "instagram"
            assert body["target"]["targetType"] == "instagram"
            assert body["content"]["mediaUrls"] == ["https://img/x.jpg"]
            return _resp({"postSubmissionId": "sub1"})
        return _resp({"status": "published", "publicUrl": "https://ig/p/1"})

    monkeypatch.setattr(p, "_request", fake_request)
    res = p.publish_post("98432", _content(extra={"blotato_account_id": "98432"},
                                          media_urls=["https://img/x.jpg"]))
    assert res.platform_post_id == "sub1"
    assert res.url == "https://ig/p/1"
    assert any(u.endswith("/posts/sub1") for _, u, _ in calls)  # polled


def test_publish_failed_raises_publish_error(monkeypatch):
    p = BlotatoInstagramProvider({"api_key": "k"})

    def fake_request(method, url, **kw):
        if url.endswith("/posts"):
            return _resp({"postSubmissionId": "sub2"})
        return _resp({"status": "failed", "errorMessage": "caption too long"})

    monkeypatch.setattr(p, "_request", fake_request)
    with pytest.raises(PublishError, match="caption too long"):
        p.publish_post("98432", _content(extra={"blotato_account_id": "98432"}))


def test_publish_timeout_raises_still_publishing(monkeypatch):
    monkeypatch.setattr("providers.blotato.time.sleep", lambda *_: None)
    monkeypatch.setattr("providers.blotato.time.monotonic", _fake_clock())
    p = BlotatoInstagramProvider({"api_key": "k"})

    def fake_request(method, url, **kw):
        if url.endswith("/posts"):
            return _resp({"postSubmissionId": "sub3"})
        return _resp({"status": "in-progress"})

    monkeypatch.setattr(p, "_request", fake_request)
    with pytest.raises(BlotatoStillPublishing) as ei:
        p.publish_post("98432", _content(extra={"blotato_account_id": "98432"}))
    assert ei.value.submission_id == "sub3"


def test_facebook_target_includes_page_id(monkeypatch):
    p = BlotatoFacebookProvider({"api_key": "k"})
    captured = {}

    def fake_request(method, url, **kw):
        if url.endswith("/posts"):
            captured["target"] = kw["json"]["post"]["target"]
            return _resp({"postSubmissionId": "s"})
        return _resp({"status": "published", "publicUrl": "u"})

    monkeypatch.setattr(p, "_request", fake_request)
    p.publish_post("1", _content(extra={"blotato_account_id": "1", "page_id": "PAGE9"}))
    assert captured["target"] == {"targetType": "facebook", "pageId": "PAGE9"}


def test_missing_account_id_fails_closed(monkeypatch):
    p = BlotatoInstagramProvider({"api_key": "k"})
    with pytest.raises(PublishError, match="account"):
        p.publish_post("", _content(extra={}))


def _fake_clock():
    # monotonic() returns 0 then jumps past the timeout on the 2nd+ call.
    state = {"t": 0}
    def clock():
        state["t"] += 100
        return state["t"]
    return clock
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/macbook/.local/bin/uv run pytest providers/tests/test_blotato_provider.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'providers.blotato'`.

- [ ] **Step 3: Implement `providers/blotato.py`**

```python
"""Blotato multi-platform publishing provider (add-on family).

Blotato (https://backend.blotato.com/v2) publishes to many networks behind a
single workspace API key. Accounts are connected in Blotato's dashboard and
referenced by accountId. One BlotatoProvider base + per-target subclasses
registered as ``blotato_<target>``. The engine injects per-account data
(blotato_account_id, page_id) via ``content.extra``. Publishing is async:
submit to POST /posts, poll GET /posts/{id}; on timeout raise
BlotatoStillPublishing so the engine parks the post for the reconcile task.
"""
from __future__ import annotations

import logging
import os
import time

from django.conf import settings

from .base import SocialProvider
from .exceptions import BlotatoStillPublishing, PublishError
from .types import AccountProfile, AuthType, MediaType, PostType, PublishContent, PublishResult

logger = logging.getLogger(__name__)


def _api_base() -> str:
    return getattr(settings, "BLOTATO_API_BASE", "https://backend.blotato.com/v2").rstrip("/")


class BlotatoProvider(SocialProvider):
    """Base for all Blotato targets. Subclasses set ``target_type`` + metadata."""

    target_type: str = ""
    _label: str = "Blotato"
    _max_caption: int = 2200

    @property
    def platform_name(self) -> str:
        return self._label

    @property
    def auth_type(self) -> AuthType:
        return AuthType.API_KEY

    @property
    def max_caption_length(self) -> int:
        return self._max_caption

    @property
    def supported_post_types(self) -> list[PostType]:
        return [PostType.TEXT, PostType.IMAGE, PostType.VIDEO]

    @property
    def supported_media_types(self) -> list[MediaType]:
        return [MediaType.JPEG, MediaType.PNG, MediaType.GIF, MediaType.MP4, MediaType.MOV]

    @property
    def required_scopes(self) -> list[str]:
        return []

    # Blotato manages each network's connection health on its side; our health
    # signal is publish success/failure, so don't fail the account on a profile
    # probe that can't see the per-account key in the health path.
    def validate_token(self, access_token: str) -> bool:
        return True

    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        api_key = self.credentials.get("api_key", "")
        if not api_key:
            raise PublishError("Blotato API key is not configured", platform=self.platform_name)
        return {"blotato-api-key": api_key}

    def get_profile(self, access_token: str) -> AccountProfile:
        resp = self._request("GET", f"{_api_base()}/users/me/accounts", headers=self._headers())
        for acct in resp.json().get("items", []):
            if str(acct.get("id")) == str(access_token):
                return AccountProfile(platform_id=str(acct["id"]),
                                      name=acct.get("fullname", ""), handle=acct.get("username"))
        return AccountProfile(platform_id=str(access_token), name="", handle=None)

    def _resolve_media_urls(self, content: PublishContent) -> list[str]:
        # Prefer already-public URLs; otherwise upload local files via /media.
        if content.media_urls:
            return list(content.media_urls)
        urls: list[str] = []
        for path in content.media_files or []:
            r = self._request("POST", f"{_api_base()}/media",
                              headers=self._headers(), json={"filename": os.path.basename(path)})
            data = r.json()
            with open(path, "rb") as fh:
                self._request("PUT", data["presignedUrl"], data=fh.read())
            urls.append(data["publicUrl"])
        return urls

    def _build_target(self, content: PublishContent) -> dict:
        return {"targetType": self.target_type}

    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        account_id = content.extra.get("blotato_account_id") or access_token
        if not account_id:
            raise PublishError("Missing Blotato account id", platform=self.platform_name)
        media_urls = self._resolve_media_urls(content)
        body = {
            "post": {
                "accountId": str(account_id),
                "content": {
                    "text": content.text or "",
                    "mediaUrls": media_urls,
                    "platform": self.target_type,
                },
                "target": self._build_target(content),
            }
        }
        resp = self._request("POST", f"{_api_base()}/posts", headers=self._headers(), json=body)
        data = resp.json()
        submission_id = str(data.get("postSubmissionId") or data.get("id") or "")
        if not submission_id:
            raise PublishError(f"Blotato returned no submission id: {resp.text[:300]}",
                               platform=self.platform_name)
        return self._poll_until_done(submission_id)

    def check_status(self, submission_id: str) -> dict:
        """One status read — used by publish polling and the reconcile task."""
        return self._request("GET", f"{_api_base()}/posts/{submission_id}",
                             headers=self._headers()).json()

    def _poll_until_done(self, submission_id: str) -> PublishResult:
        timeout = getattr(settings, "BLOTATO_PUBLISH_TIMEOUT", 30)
        interval = getattr(settings, "BLOTATO_POLL_INTERVAL", 2)
        deadline = time.monotonic() + timeout
        while True:
            data = self.check_status(submission_id)
            status = (data.get("status") or "").lower()
            if status == "published":
                return PublishResult(platform_post_id=submission_id,
                                     url=data.get("publicUrl"), extra=data)
            if status == "failed":
                raise PublishError(data.get("errorMessage") or "Blotato publish failed",
                                   platform=self.platform_name, raw_response=data)
            if time.monotonic() >= deadline:
                raise BlotatoStillPublishing(submission_id, platform=self.platform_name)
            time.sleep(interval)


class BlotatoInstagramProvider(BlotatoProvider):
    target_type = "instagram"
    _label = "Instagram (Blotato)"
    _max_caption = 2200


class BlotatoFacebookProvider(BlotatoProvider):
    target_type = "facebook"
    _label = "Facebook (Blotato)"
    _max_caption = 63206

    def _build_target(self, content: PublishContent) -> dict:
        target = {"targetType": "facebook"}
        page_id = content.extra.get("page_id")
        if page_id:
            target["pageId"] = page_id
        return target


class BlotatoThreadsProvider(BlotatoProvider):
    target_type = "threads"
    _label = "Threads (Blotato)"
    _max_caption = 500

    def _build_target(self, content: PublishContent) -> dict:
        target = {"targetType": "threads"}
        reply_control = content.extra.get("reply_control")
        if reply_control:
            target["replyControl"] = reply_control
        return target


class BlotatoBlueskyProvider(BlotatoProvider):
    target_type = "bluesky"
    _label = "Bluesky (Blotato)"
    _max_caption = 300


class BlotatoLinkedInProvider(BlotatoProvider):
    target_type = "linkedin"
    _label = "LinkedIn (Blotato)"
    _max_caption = 3000
```

In `providers/__init__.py`, add the imports near the other provider imports and extend the registry. After the `PROVIDER_REGISTRY = {...}` literal, add:
```python
from .blotato import (
    BlotatoBlueskyProvider,
    BlotatoFacebookProvider,
    BlotatoInstagramProvider,
    BlotatoLinkedInProvider,
    BlotatoThreadsProvider,
)

PROVIDER_REGISTRY.update({
    "blotato_instagram": BlotatoInstagramProvider,
    "blotato_facebook": BlotatoFacebookProvider,
    "blotato_threads": BlotatoThreadsProvider,
    "blotato_bluesky": BlotatoBlueskyProvider,
    "blotato_linkedin": BlotatoLinkedInProvider,
})
```
(Place the `from .blotato import ...` with the other top-level provider imports if the linter prefers; functionally either works since `PROVIDER_REGISTRY` is a module global.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/macbook/.local/bin/uv run pytest providers/tests/test_blotato_provider.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add providers/blotato.py providers/__init__.py providers/tests/test_blotato_provider.py
git commit -m "feat(providers): Blotato provider family (instagram/facebook/threads/bluesky/linkedin)"
```

---

### Task 4: Engine credential-resolution branch

**Files:**
- Modify: `apps/publisher/engine.py` (`_resolve_publish_credentials`, ~line 78-119)
- Test: `apps/publisher/tests/test_blotato_credentials.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/publisher/tests/test_blotato_credentials.py
import pytest
from django.test import override_settings


@pytest.fixture
def account(db):
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    return SocialAccount.objects.create(
        workspace=ws, platform="blotato_instagram",
        account_platform_id="98432", account_name="AfCEN")


@pytest.mark.django_db
@override_settings(BLOTATO_API_KEY="env-key-123")
def test_blotato_credentials_fall_back_to_env(account):
    from apps.publisher.engine import _resolve_publish_credentials
    creds = _resolve_publish_credentials(account)
    assert creds == {"api_key": "env-key-123"}


@pytest.mark.django_db
def test_blotato_credentials_prefer_platform_credential(account):
    from apps.credentials.models import PlatformCredential
    from apps.publisher.engine import _resolve_publish_credentials
    PlatformCredential.objects.create(
        organization=account.workspace.organization, platform="blotato",
        credentials={"api_key": "org-key-999"}, is_configured=True)
    creds = _resolve_publish_credentials(account)
    assert creds == {"api_key": "org-key-999"}
```

> NOTE: confirm the `PlatformCredential` create kwargs (`organization`, `is_configured`) match the model; adjust to the model's real fields/manager (`PlatformCredential.objects.for_org(...)`) if needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/publisher/tests/test_blotato_credentials.py -q -p no:warnings --reuse-db`
Expected: FAIL — returns `{}` (no blotato branch), not `{"api_key": ...}`.

- [ ] **Step 3: Add the branch**

In `apps/publisher/engine.py`, at the TOP of `_resolve_publish_credentials`, right after `platform = account.platform`:
```python
    # Blotato is a single-key, multi-target provider family. Every blotato_*
    # account shares one org-level key (PlatformCredential(platform="blotato"))
    # with an env fallback. There are no per-account OAuth tokens.
    if platform.startswith("blotato_"):
        api_key = ""
        try:
            cred = PlatformCredential.objects.for_org(
                account.workspace.organization_id
            ).get(platform="blotato", is_configured=True)
            api_key = cred.credentials.get("api_key", "")
        except PlatformCredential.DoesNotExist:
            api_key = getattr(settings, "BLOTATO_API_KEY", "")
        return {"api_key": api_key}
```
Ensure `from django.conf import settings` is imported at the top of `engine.py` (it is — used by `APP_URL`).

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/publisher/tests/test_blotato_credentials.py -q -p no:warnings --reuse-db`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/publisher/engine.py apps/publisher/tests/test_blotato_credentials.py
git commit -m "feat(publisher): resolve Blotato API key for blotato_* platforms"
```

---

### Task 5: Engine extras-injection branch (accountId + Facebook pageId)

**Files:**
- Modify: `apps/publisher/engine.py` (the extras block ~line 562-572, after facebook/linkedin_company injects)
- Test: `apps/publisher/tests/test_blotato_extras.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/publisher/tests/test_blotato_extras.py
import pytest


def _make(db_platform, provider_config):
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    return SocialAccount.objects.create(
        workspace=ws, platform=db_platform, account_platform_id="98432",
        account_name="AfCEN", provider_config=provider_config)


@pytest.mark.django_db
def test_blotato_extras_injects_account_id_and_page_id():
    from apps.publisher.engine import _blotato_extra
    acct = _make("blotato_facebook", {"blotato_account_id": "98432", "page_id": "PAGE7"})
    extra = {}
    _blotato_extra(acct, "blotato_facebook", extra)
    assert extra["blotato_account_id"] == "98432"
    assert extra["page_id"] == "PAGE7"


@pytest.mark.django_db
def test_blotato_extras_account_id_falls_back_to_platform_id():
    from apps.publisher.engine import _blotato_extra
    acct = _make("blotato_instagram", {})
    extra = {}
    _blotato_extra(acct, "blotato_instagram", extra)
    assert extra["blotato_account_id"] == "98432"
    assert "page_id" not in extra
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/publisher/tests/test_blotato_extras.py -q -p no:warnings --reuse-db`
Expected: FAIL — `ImportError` (`_blotato_extra` not defined).

- [ ] **Step 3: Add the helper + call it from the extras block**

In `apps/publisher/engine.py`, add a module-level helper (near `_resolve_publish_credentials`):
```python
def _blotato_extra(account, platform: str, extra: dict) -> None:
    """Inject per-account Blotato data into the provider content extras."""
    cfg = account.provider_config or {}
    extra["blotato_account_id"] = cfg.get("blotato_account_id") or account.account_platform_id
    if platform == "blotato_facebook" and "page_id" not in extra:
        page_id = cfg.get("page_id")
        if page_id:
            extra["page_id"] = page_id
```

Then, in the extras-injection block of `_dispatch_to_provider` (right after the existing `linkedin_company` author injection, before `link_url = extra.pop(...)`), add:
```python
            # Inject Blotato per-account data for blotato_* platforms.
            if platform.startswith("blotato_"):
                _blotato_extra(account, platform, extra)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/publisher/tests/test_blotato_extras.py -q -p no:warnings --reuse-db`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/publisher/engine.py apps/publisher/tests/test_blotato_extras.py
git commit -m "feat(publisher): inject Blotato accountId + Facebook pageId into content.extra"
```

---

### Task 6: Park at `publishing` on `BlotatoStillPublishing` (no retry, no dupe)

**Files:**
- Modify: `apps/publisher/engine.py` (`_publish_platform_post`, the try/except ~line 328-389)
- Test: `apps/publisher/tests/test_blotato_park.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/publisher/tests/test_blotato_park.py
from unittest.mock import patch

import pytest


@pytest.fixture
def blotato_pp(db):
    from datetime import timedelta
    from django.utils import timezone
    from apps.composer.models import PlatformPost, Post
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    acct = SocialAccount.objects.create(
        workspace=ws, platform="blotato_instagram", account_platform_id="98432",
        account_name="AfCEN", connection_status=SocialAccount.ConnectionStatus.CONNECTED)
    post = Post.objects.create(workspace=ws, caption="hello")
    return PlatformPost.objects.create(
        post=post, social_account=acct, status=PlatformPost.Status.SCHEDULED,
        scheduled_at=timezone.now() - timedelta(minutes=1))


@pytest.mark.django_db
def test_still_publishing_parks_at_publishing_without_retry(blotato_pp):
    from apps.composer.models import PlatformPost
    from apps.publisher.engine import PublishEngine
    from providers.exceptions import BlotatoStillPublishing

    with patch.object(PublishEngine, "_dispatch_to_provider",
                      side_effect=BlotatoStillPublishing("sub_99")), \
         patch.object(PublishEngine, "_schedule_retry") as retry:
        PublishEngine()._publish_platform_post(blotato_pp)

    blotato_pp.refresh_from_db()
    assert blotato_pp.status == PlatformPost.Status.PUBLISHING
    assert blotato_pp.platform_post_id == "sub_99"
    retry.assert_not_called()  # parked for reconcile, NOT retried
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/publisher/tests/test_blotato_park.py -q -p no:warnings --reuse-db`
Expected: FAIL — generic `except Exception` schedules a retry and leaves status unchanged.

- [ ] **Step 3: Add the except clause**

At the top of `apps/publisher/engine.py`, add to the providers import:
```python
from providers.exceptions import BlotatoStillPublishing
```
In `_publish_platform_post`, add this clause BEFORE the existing `except Exception as e:`:
```python
        except BlotatoStillPublishing as e:
            # Blotato accepted the post but it's still in-progress. Park at
            # publishing + persist the submission id; the reconcile task
            # finalizes it. Never re-submit (would duplicate the post).
            platform_post.platform_post_id = e.submission_id
            platform_post.status = PlatformPost.Status.PUBLISHING
            platform_post.publish_error = ""
            platform_post.save(update_fields=["platform_post_id", "status", "publish_error", "updated_at"])
            PublishLog.objects.create(
                platform_post=platform_post,
                attempt_number=platform_post.retry_count + 1,
                error_message=f"Blotato in-progress ({e.submission_id}); awaiting reconcile",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
            return {"success": False, "pending": True, "platform_post_id": e.submission_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/publisher/tests/test_blotato_park.py -q -p no:warnings --reuse-db`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/publisher/engine.py apps/publisher/tests/test_blotato_park.py
git commit -m "feat(publisher): park Blotato in-progress posts at publishing for reconcile"
```

---

### Task 7: Reconcile beat task

**Files:**
- Modify: `apps/publisher/tasks.py` (add `reconcile_blotato_posts`)
- Modify: `jobs/schedules.py` (add `blotato-reconcile`)
- Test: `apps/publisher/tests/test_blotato_reconcile.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/publisher/tests/test_blotato_reconcile.py
from unittest.mock import MagicMock, patch

import pytest


def _pp(db, status_field):
    from apps.composer.models import PlatformPost, Post
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    acct = SocialAccount.objects.create(
        workspace=ws, platform="blotato_instagram", account_platform_id="1", account_name="A")
    post = Post.objects.create(workspace=ws, caption="x")
    return PlatformPost.objects.create(
        post=post, social_account=acct, status=PlatformPost.Status.PUBLISHING,
        platform_post_id="sub_42")


@pytest.mark.django_db
def test_reconcile_finalizes_published(db):
    from apps.composer.models import PlatformPost
    from apps.publisher.tasks import reconcile_blotato_posts
    pp = _pp(db, "publishing")
    fake = MagicMock()
    fake.check_status.return_value = {"status": "published", "publicUrl": "https://ig/1"}
    with patch("apps.publisher.tasks.get_provider", return_value=fake), \
         patch("apps.publisher.tasks._resolve_publish_credentials", return_value={"api_key": "k"}):
        reconcile_blotato_posts()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.PUBLISHED
    assert pp.published_at is not None


@pytest.mark.django_db
def test_reconcile_finalizes_failed(db):
    from apps.composer.models import PlatformPost
    from apps.publisher.tasks import reconcile_blotato_posts
    pp = _pp(db, "publishing")
    fake = MagicMock()
    fake.check_status.return_value = {"status": "failed", "errorMessage": "rejected"}
    with patch("apps.publisher.tasks.get_provider", return_value=fake), \
         patch("apps.publisher.tasks._resolve_publish_credentials", return_value={"api_key": "k"}):
        reconcile_blotato_posts()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.FAILED
    assert "rejected" in pp.publish_error


@pytest.mark.django_db
def test_reconcile_leaves_in_progress(db):
    from apps.composer.models import PlatformPost
    from apps.publisher.tasks import reconcile_blotato_posts
    pp = _pp(db, "publishing")
    fake = MagicMock()
    fake.check_status.return_value = {"status": "in-progress"}
    with patch("apps.publisher.tasks.get_provider", return_value=fake), \
         patch("apps.publisher.tasks._resolve_publish_credentials", return_value={"api_key": "k"}):
        reconcile_blotato_posts()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.PUBLISHING  # untouched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/publisher/tests/test_blotato_reconcile.py -q -p no:warnings --reuse-db`
Expected: FAIL — `ImportError` (`reconcile_blotato_posts` not defined).

- [ ] **Step 3: Implement the task**

Append to `apps/publisher/tasks.py` (match the existing `@shared_task` style + imports there):
```python
@shared_task
def reconcile_blotato_posts():
    """Finalize Blotato posts parked at 'publishing' by polling their status.

    Idempotent and never re-submits — it only reads GET /posts/{id} and moves
    the PlatformPost to published/failed once Blotato reports a terminal state.
    """
    from django.utils import timezone

    from apps.composer.models import PlatformPost
    from apps.publisher.engine import _resolve_publish_credentials
    from providers import get_provider

    qs = PlatformPost.objects.filter(
        status=PlatformPost.Status.PUBLISHING,
        social_account__platform__startswith="blotato_",
    ).exclude(platform_post_id="").select_related("social_account__workspace__organization")

    for pp in qs:
        try:
            creds = _resolve_publish_credentials(pp.social_account)
            provider = get_provider(pp.social_account.platform, creds)
            data = provider.check_status(pp.platform_post_id)
        except Exception:  # noqa: BLE001 - one bad row must not stall the sweep
            logging.getLogger(__name__).warning(
                "blotato reconcile failed for %s", pp.id, exc_info=True)
            continue
        status = (data.get("status") or "").lower()
        if status == "published":
            pp.status = PlatformPost.Status.PUBLISHED
            pp.published_at = timezone.now()
            pp.publish_error = ""
            pp.save(update_fields=["status", "published_at", "publish_error", "updated_at"])
        elif status == "failed":
            pp.status = PlatformPost.Status.FAILED
            pp.publish_error = data.get("errorMessage") or "Blotato publish failed"
            pp.save(update_fields=["status", "publish_error", "updated_at"])
        # else still in-progress → leave for the next sweep
```
Ensure `import logging` and `from celery import shared_task` are present at the top of `tasks.py` (they are — used by other tasks). The test patches `apps.publisher.tasks.get_provider` and `apps.publisher.tasks._resolve_publish_credentials`, so import them at MODULE level too:
```python
from apps.publisher.engine import _resolve_publish_credentials  # noqa: E402 (top of file)
from providers import get_provider  # noqa: E402
```
(If top-level import causes a circular import, keep them inside the function AND update the test to patch where they're used — but module-level is preferred; verify no circular import by running the test.)

In `jobs/schedules.py`, add to `BEAT_SCHEDULE`:
```python
    "blotato-reconcile": {
        # Finalize Blotato posts parked at 'publishing' (async publish that
        # didn't complete within the inline poll window). Never re-submits.
        "task": "apps.publisher.tasks.reconcile_blotato_posts",
        "schedule": schedule(run_every=60),
    },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/publisher/tests/test_blotato_reconcile.py -q -p no:warnings --reuse-db`
Expected: PASS (3)
Also run the beat schedule test to confirm the entry is valid:
`DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest tests/test_beat_schedule.py -q -p no:warnings --reuse-db`

- [ ] **Step 5: Commit**

```bash
git add apps/publisher/tasks.py jobs/schedules.py apps/publisher/tests/test_blotato_reconcile.py
git commit -m "feat(publisher): blotato-reconcile beat task finalizes parked posts"
```

---

### Task 8: Connect Blotato + import accounts

**Files:**
- Modify: `apps/credentials/platform_fields.py` (add `blotato` entry)
- Create: `apps/social_accounts/blotato_client.py` (thin list/subaccounts helper)
- Modify: `apps/social_accounts/views.py` (add `blotato_import` GET/POST)
- Modify: `apps/social_accounts/urls.py` (add route)
- Create: `templates/social_accounts/blotato_import.html`
- Test: `apps/social_accounts/tests/test_blotato_import.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/social_accounts/tests/test_blotato_import.py
from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.fixture
def authed(client, db):
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    u = User.objects.create_user(email="a@x.io", password="pw", name="A",
                                 tos_accepted_at=timezone.now())
    OrgMembership.objects.create(user=u, organization=org, org_role=OrgMembership.OrgRole.OWNER)
    WorkspaceMembership.objects.create(user=u, workspace=ws, workspace_role="owner")
    u.last_workspace_id = ws.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return client, ws


ACCOUNTS = {"items": [
    {"id": "111", "platform": "instagram", "fullname": "AfCEN IG", "username": "afcen"},
    {"id": "222", "platform": "facebook", "fullname": "AfCEN FB", "username": "afcenfb"},
    {"id": "333", "platform": "tiktok", "fullname": "AfCEN TT", "username": "afcentt"},
]}


@pytest.mark.django_db
def test_import_lists_supported_accounts(authed):
    client, ws = authed
    with patch("apps.social_accounts.views.blotato_list_accounts", return_value=ACCOUNTS["items"]):
        resp = client.get(reverse("social_accounts:blotato_import", args=[ws.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "AfCEN IG" in body and "AfCEN FB" in body
    # tiktok is out of MVP scope -> shown disabled / not importable
    assert "AfCEN TT" not in body or "not yet supported" in body.lower()


@pytest.mark.django_db
def test_import_creates_social_accounts_with_pageid(authed):
    client, ws = authed
    from apps.social_accounts.models import SocialAccount
    with patch("apps.social_accounts.views.blotato_list_accounts", return_value=ACCOUNTS["items"]), \
         patch("apps.social_accounts.views.blotato_subaccount_page_id", return_value="PAGE_X"):
        resp = client.post(reverse("social_accounts:blotato_import", args=[ws.id]),
                           {"account_id": ["111", "222"]})
    assert resp.status_code in (302, 200)
    ig = SocialAccount.objects.get(workspace=ws, platform="blotato_instagram")
    assert ig.account_platform_id == "111"
    assert ig.provider_config["blotato_account_id"] == "111"
    fb = SocialAccount.objects.get(workspace=ws, platform="blotato_facebook")
    assert fb.provider_config["page_id"] == "PAGE_X"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/social_accounts/tests/test_blotato_import.py -q -p no:warnings --reuse-db`
Expected: FAIL — `NoReverseMatch`/`ImportError`.

- [ ] **Step 3: Implement client + view + url + template + credential field**

Create `apps/social_accounts/blotato_client.py`:
```python
"""Thin Blotato account-discovery client for the import flow."""
from __future__ import annotations

import httpx
from django.conf import settings


def _base() -> str:
    return getattr(settings, "BLOTATO_API_BASE", "https://backend.blotato.com/v2").rstrip("/")


def _api_key(organization_id) -> str:
    from apps.credentials.models import PlatformCredential
    try:
        cred = PlatformCredential.objects.for_org(organization_id).get(
            platform="blotato", is_configured=True)
        key = cred.credentials.get("api_key", "")
        if key:
            return key
    except PlatformCredential.DoesNotExist:
        pass
    return getattr(settings, "BLOTATO_API_KEY", "")


def blotato_list_accounts(organization_id) -> list[dict]:
    key = _api_key(organization_id)
    if not key:
        return []
    with httpx.Client(timeout=15.0) as c:
        r = c.get(f"{_base()}/users/me/accounts", headers={"blotato-api-key": key})
        r.raise_for_status()
        return r.json().get("items", [])


def blotato_subaccount_page_id(organization_id, account_id) -> str:
    key = _api_key(organization_id)
    if not key:
        return ""
    with httpx.Client(timeout=15.0) as c:
        r = c.get(f"{_base()}/users/me/accounts/{account_id}/subaccounts",
                  headers={"blotato-api-key": key})
        if r.status_code != 200:
            return ""
        items = r.json().get("items", [])
        return str(items[0].get("pageId")) if items else ""
```

Add to `apps/credentials/platform_fields.py` `PLATFORM_FIELDS`:
```python
    "blotato": {
        "label": "Blotato (multi-platform publishing)",
        "help": "blotato.com → Settings → API. Paste your workspace API key "
                "(it may end with '='; include it). Then import accounts.",
        "fields": [
            ("api_key", "API Key", "password"),
        ],
    },
```

In `apps/social_accounts/views.py`, add the import + view (MVP-supported targets only):
```python
from apps.social_accounts.blotato_client import (  # noqa: E402
    blotato_list_accounts,
    blotato_subaccount_page_id,
)

# Blotato target platforms we support importing (MVP).
_BLOTATO_SUPPORTED = {"instagram", "facebook", "threads", "bluesky", "linkedin"}


@login_required
def blotato_import(request, workspace_id):
    """List the workspace's Blotato-connected accounts and import selected ones."""
    workspace = get_object_or_404(Workspace, id=workspace_id)
    org_id = workspace.organization_id
    items = blotato_list_accounts(org_id)
    supported = [a for a in items if a.get("platform") in _BLOTATO_SUPPORTED]

    if request.method == "POST":
        chosen = set(request.POST.getlist("account_id"))
        created = 0
        for a in supported:
            if str(a.get("id")) not in chosen:
                continue
            target = a["platform"]
            cfg = {"blotato_account_id": str(a["id"])}
            if target == "facebook":
                page_id = blotato_subaccount_page_id(org_id, a["id"])
                if page_id:
                    cfg["page_id"] = page_id
            SocialAccount.objects.update_or_create(
                workspace=workspace, platform=f"blotato_{target}",
                account_platform_id=str(a["id"]),
                defaults={
                    "account_name": a.get("fullname", ""),
                    "account_handle": a.get("username", ""),
                    "connection_status": SocialAccount.ConnectionStatus.CONNECTED,
                    "provider_config": cfg,
                },
            )
            created += 1
        messages.success(request, f"Imported {created} Blotato account(s).")
        return redirect("social_accounts:list", workspace_id=workspace.id)

    return render(request, "social_accounts/blotato_import.html", {
        "workspace_id": workspace.id,
        "accounts": supported,
        "has_key": bool(items) or bool(blotato_list_accounts(org_id) is not None),
    })
```
> Ensure `Workspace`, `messages`, `get_object_or_404`, `redirect`, `render`, `login_required`, `SocialAccount` are imported in `views.py` (most already are; add `from django.contrib import messages` and `from apps.workspaces.models import Workspace` if missing).

Add to `apps/social_accounts/urls.py` urlpatterns:
```python
    path(
        "<uuid:workspace_id>/blotato/import/",
        views.blotato_import,
        name="blotato_import",
    ),
```

Create `templates/social_accounts/blotato_import.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="p-6 max-w-2xl">
  <h1 class="text-2xl font-bold mb-1" style="font-family:Georgia,serif;">Import Blotato accounts</h1>
  <p class="text-sm text-stone-500 mb-4">Accounts you connected in Blotato. Pick the ones to publish to from here — every post still goes through the compliance gate.</p>

  {% if not accounts %}
  <div class="card p-4 text-sm text-stone-500">
    No importable Blotato accounts found. Add your Blotato API key under
    <a class="text-[var(--primary)] hover:underline" href="/console/credentials">Credentials</a>,
    connect accounts in your Blotato dashboard, then reload.
  </div>
  {% else %}
  <form method="post" class="space-y-2">
    {% csrf_token %}
    {% for a in accounts %}
    <label class="card p-3 flex items-center gap-3 cursor-pointer">
      <input type="checkbox" name="account_id" value="{{ a.id }}">
      <div>
        <div class="font-medium">{{ a.fullname }}</div>
        <div class="text-xs text-stone-500">{{ a.platform }} · @{{ a.username }}</div>
      </div>
    </label>
    {% endfor %}
    <button type="submit" class="btn-brand rounded px-4 py-2 text-sm mt-2">Import selected</button>
  </form>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest apps/social_accounts/tests/test_blotato_import.py -q -p no:warnings --reuse-db`
Expected: PASS (2). Fix the `has_key`/import-detection logic if the empty-state test needs adjusting — keep the view simple: if `items` is empty, render the empty state.

- [ ] **Step 5: Commit**

```bash
git add apps/social_accounts/blotato_client.py apps/social_accounts/views.py apps/social_accounts/urls.py apps/credentials/platform_fields.py templates/social_accounts/blotato_import.html apps/social_accounts/tests/test_blotato_import.py
git commit -m "feat(social): connect Blotato + import accounts flow"
```

---

### Task 9: Full-suite gate + finishing

- [ ] **Step 1: Run the full suite (isolated DB)**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test_iso /Users/macbook/.local/bin/uv run pytest -q -p no:warnings --no-header --reuse-db`
Expected: all pass (prior baseline 1639 + the new Blotato tests). Fix any regressions.

- [ ] **Step 2: Remove the throwaway settings shim**

```bash
rm -f config/settings/test_iso.py
```

- [ ] **Step 3: Merge + deploy**

```bash
git checkout main && git merge --ff-only feature/blotato-integration && git push origin main
railway up --service web --detach
railway up --service worker --detach   # so the reconcile beat task + worker pick up the new code
```

- [ ] **Step 4: Configure + smoke-test in prod**

- Set `BLOTATO_API_KEY` in Railway (web + worker) OR add it via the in-app Credentials page (platform "blotato").
- Connect Instagram/Facebook/Threads/Bluesky/personal-LinkedIn in the Blotato dashboard.
- Visit `/social-accounts/<workspace_id>/blotato/import/`, import the accounts.
- Compose a post targeting a Blotato account → approve through the gate → confirm it publishes (status → published, public URL recorded). Verify a parked post (if any) is finalized by `blotato-reconcile` within ~1 min.

---

## Self-Review

**Spec coverage:** providers (T3) ✓; credentials/API key (T4) ✓; provider_config + per-account data (T1) ✓; extras seam (T5) ✓; async submit/poll + park (T3, T6) ✓; reconcile (T7) ✓; connect/import (T8) ✓; gate untouched (no gate edits anywhere) ✓; MVP platform set instagram/facebook/threads/bluesky/linkedin ✓; out-of-scope TikTok/YouTube/Pinterest + analytics not built ✓.

**Placeholder scan:** none — every step has runnable code/commands. Two flagged verification NOTES (PlatformCredential kwargs in T4; module-vs-inline import for patching in T7) are explicit "confirm against the model and adjust" instructions, not deferred work.

**Type consistency:** `target_type`, `_build_target`, `check_status`, `_poll_until_done`, `BlotatoStillPublishing.submission_id`, `provider_config`, `_blotato_extra`, `blotato_list_accounts`, `blotato_subaccount_page_id` are used consistently across tasks. Registry keys (`blotato_<target>`) match the engine branches (`platform.startswith("blotato_")`) and the import view (`f"blotato_{target}"`).
