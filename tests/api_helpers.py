"""Lightweight helpers for exercising the Agent API from top-level tests.

Models the fixtures in ``apps/api/tests/test_routers.py`` (issue a key,
hit the router through a HTTPS-forcing Django test client) but packages
them as plain callables so a test module can mint a key + fire a request
without dragging the whole fixture tree in.
"""

from __future__ import annotations

import json
import uuid
from typing import NamedTuple

from django.test import Client
from django.utils import timezone


class IssuedKey(NamedTuple):
    """Test handle bundling the plaintext token, the persisted key, and the
    single allowlisted ``SocialAccount`` so callers can reference its ID."""

    plaintext_token: str
    api_key: object
    social_account: object


class _SecureClient(Client):
    """Django test client that forces ``secure=True`` on every request.

    Mirrors ``apps/api/tests/test_routers.py::_SecureClient`` so the
    production HTTPS guard in ``ApiKeyAuth`` is satisfied.
    """

    def generic(self, method, path, *args, **kwargs):
        kwargs["secure"] = True
        return super().generic(method, path, *args, **kwargs)


def make_api_key(*, perms: list[str] | None = None):
    """Create an Org → Workspace → SocialAccount → API key chain.

    Returns the ``IssuedApiKey`` (carrying ``.plaintext_token`` and the
    persisted ``.api_key``). The single allowlisted ``SocialAccount`` is
    reachable via ``result.social_account`` for tests that need its ID.
    """
    from apps.accounts.models import User
    from apps.api_keys import services
    from apps.members.models import PERMISSION_KEYS, OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    suffix = uuid.uuid4().hex[:8]
    user = User.objects.create_user(
        email=f"gate-{suffix}@example.com",
        password="testpass123",
        name="Gate Tester",
        tos_accepted_at=timezone.now(),
    )
    organization = Organization.objects.create(name=f"Gate Org {suffix}")
    workspace = Workspace.objects.create(name=f"Gate WS {suffix}", organization=organization)
    OrgMembership.objects.create(
        user=user, organization=organization, org_role=OrgMembership.OrgRole.OWNER
    )
    WorkspaceMembership.objects.create(
        user=user,
        workspace=workspace,
        workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
    )
    social_account = SocialAccount.objects.create(
        workspace=workspace,
        platform="linkedin_personal",
        account_platform_id=f"li-{suffix}",
        account_name="Gate LinkedIn",
        connection_status="connected",
    )
    issued = services.issue_api_key(
        workspace=workspace,
        social_accounts=[social_account],
        issued_by=user,
        name=f"gate-{suffix}",
        permissions=list(perms) if perms is not None else list(PERMISSION_KEYS),
    )
    return IssuedKey(
        plaintext_token=issued.plaintext_token,
        api_key=issued.api_key,
        social_account=social_account,
    )


def api_post(path: str, key, body: dict):
    """POST ``body`` (JSON) to ``path`` authenticated as ``key``."""
    client = _SecureClient(HTTP_AUTHORIZATION=f"Bearer {key.plaintext_token}")
    return client.post(path, data=json.dumps(body), content_type="application/json")
