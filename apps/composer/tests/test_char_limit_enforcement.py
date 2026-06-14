"""Per-platform caption-limit enforcement at the service + API layer.

The platform char limits were *defined* (``SocialAccount.PLATFORM_CHAR_LIMITS``)
and *displayed* (composer client counter) but never enforced server-side.
A caption pasted via the Agent API or built by the agent could silently sail
past the platform limit and only fail (or be silently truncated) at publish
time. These tests pin the new server-side guard:

* ``apps/social_accounts/limits.validate_caption_length`` raises a clear error
  when ``len(text) > limit``.
* ``composer.services.create_post`` rejects an over-limit caption (honouring a
  per-account ``platform_overrides`` caption too).
* ``POST/PATCH /api/v1/.../posts`` return 422 for an over-limit caption.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.utils import timezone

from apps.api_keys import services
from apps.composer.models import Post
from apps.members.models import PERMISSION_KEYS, OrgMembership, WorkspaceMembership


# ---------------------------------------------------------------------------
# Helper-level test
# ---------------------------------------------------------------------------


class TestValidateCaptionLength:
    def test_under_limit_passes(self):
        from apps.social_accounts.limits import validate_caption_length

        # No exception expected.
        validate_caption_length("hello", limit=500, platform="threads")

    def test_at_limit_passes(self):
        from apps.social_accounts.limits import validate_caption_length

        validate_caption_length("x" * 500, limit=500, platform="threads")

    def test_over_limit_raises_with_platform_and_counts(self):
        from apps.social_accounts.limits import (
            CaptionTooLongError,
            validate_caption_length,
        )

        with pytest.raises(CaptionTooLongError) as exc:
            validate_caption_length("x" * 501, limit=500, platform="threads")
        msg = str(exc.value)
        assert "threads" in msg
        assert "501" in msg
        assert "500" in msg


# ---------------------------------------------------------------------------
# Service-layer test
# ---------------------------------------------------------------------------


@pytest.fixture
def organization(db):
    from apps.organizations.models import Organization

    return Organization.objects.create(name="Limits Org")


@pytest.fixture
def workspace(db, organization):
    from apps.workspaces.models import Workspace

    return Workspace.objects.create(name="Limits WS", organization=organization)


@pytest.fixture
def social_account(db, workspace):
    from apps.social_accounts.models import SocialAccount

    # threads → 500 char limit (small, easy to overflow in a test).
    return SocialAccount.objects.create(
        workspace=workspace,
        platform="threads",
        account_platform_id="th-limits",
        account_name="Limits Threads",
        connection_status="connected",
    )


@pytest.mark.django_db
class TestCreatePostCaptionLimit:
    def test_over_limit_caption_rejected(self, workspace, social_account):
        from apps.composer.services import create_post

        with pytest.raises(ValueError) as exc:
            create_post(
                workspace=workspace,
                social_account=social_account,
                caption="x" * 501,
            )
        assert "threads" in str(exc.value)
        # Nothing persisted.
        assert Post.objects.count() == 0

    def test_at_limit_caption_accepted(self, workspace, social_account):
        from apps.composer.services import create_post

        post = create_post(
            workspace=workspace,
            social_account=social_account,
            caption="x" * 500,
        )
        assert Post.objects.filter(id=post.id).exists()

    def test_over_limit_platform_override_caption_rejected(self, workspace, social_account):
        """The per-account override caption is what actually publishes, so it
        must be validated too — a short default caption with an over-limit
        override must still be rejected."""
        from apps.composer.services import create_post

        with pytest.raises(ValueError) as exc:
            create_post(
                workspace=workspace,
                social_account=social_account,
                caption="short",
                platform_overrides={social_account.id: {"caption": "x" * 501}},
            )
        assert "threads" in str(exc.value)
        assert Post.objects.count() == 0


@pytest.mark.django_db
class TestUpdatePostCaptionLimit:
    def test_update_over_limit_caption_rejected(self, workspace, social_account):
        from apps.composer.services import create_post, update_post

        post = create_post(
            workspace=workspace,
            social_account=social_account,
            caption="ok",
        )
        with pytest.raises(ValueError) as exc:
            update_post(post=post, caption="x" * 501)
        assert "threads" in str(exc.value)
        post.refresh_from_db()
        assert post.caption == "ok"


# ---------------------------------------------------------------------------
# API-layer test (422)
# ---------------------------------------------------------------------------


class _SecureClient(Client):
    def generic(self, method, path, *args, **kwargs):
        kwargs["secure"] = True
        return super().generic(method, path, *args, **kwargs)


@pytest.fixture
def user(db):
    from apps.accounts.models import User

    return User.objects.create_user(
        email="limits@example.com",
        password="testpass123",
        name="Limits",
        tos_accepted_at=timezone.now(),
    )


@pytest.fixture
def owner_memberships(db, user, organization, workspace):
    OrgMembership.objects.create(user=user, organization=organization, org_role=OrgMembership.OrgRole.OWNER)
    return WorkspaceMembership.objects.create(
        user=user, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
    )


@pytest.fixture
def issued_key(db, user, owner_memberships, workspace, social_account):
    return services.issue_api_key(
        workspace=workspace,
        social_accounts=[social_account],
        issued_by=user,
        name="limits",
        permissions=list(PERMISSION_KEYS),
    )


@pytest.fixture
def client_with_token(issued_key):
    return _SecureClient(HTTP_AUTHORIZATION=f"Bearer {issued_key.plaintext_token}")


@pytest.mark.django_db
class TestApiCaptionLimit:
    def test_create_over_limit_returns_422(self, client_with_token, social_account):
        body = {
            "social_account_id": str(social_account.id),
            "caption": "x" * 501,
            "action": "draft",
        }
        r = client_with_token.post(
            "/api/v1/posts/", data=json.dumps(body), content_type="application/json"
        )
        assert r.status_code == 422, r.content
        assert Post.objects.count() == 0

    def test_create_at_limit_succeeds(self, client_with_token, social_account):
        body = {
            "social_account_id": str(social_account.id),
            "caption": "x" * 500,
            "action": "draft",
        }
        r = client_with_token.post(
            "/api/v1/posts/", data=json.dumps(body), content_type="application/json"
        )
        assert r.status_code == 201, r.content

    def test_create_over_limit_override_returns_422(self, client_with_token, social_account):
        body = {
            "social_account_id": str(social_account.id),
            "caption": "short",
            "action": "draft",
            "platform_overrides": [
                {
                    "social_account_id": str(social_account.id),
                    "caption": "x" * 501,
                }
            ],
        }
        r = client_with_token.post(
            "/api/v1/posts/", data=json.dumps(body), content_type="application/json"
        )
        assert r.status_code == 422, r.content
        assert Post.objects.count() == 0

    def test_patch_over_limit_returns_422(self, client_with_token, social_account):
        create = client_with_token.post(
            "/api/v1/posts/",
            data=json.dumps(
                {
                    "social_account_id": str(social_account.id),
                    "caption": "ok",
                    "action": "draft",
                }
            ),
            content_type="application/json",
        )
        assert create.status_code == 201, create.content
        post_id = create.json()["id"]

        r = client_with_token.patch(
            f"/api/v1/posts/{post_id}",
            data=json.dumps({"caption": "x" * 501}),
            content_type="application/json",
        )
        assert r.status_code == 422, r.content
