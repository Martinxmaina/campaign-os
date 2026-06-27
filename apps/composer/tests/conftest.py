"""Shared composer-test fixtures.

Provides ``make_user_in_workspace`` and ``make_post`` factories used by the
compose render-smoke test. The root ``conftest.py`` already provides the
``workspace`` fixture (a Workspace under a Test Organization).
"""
import itertools

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import Post
from apps.members.models import WorkspaceMembership

_email_counter = itertools.count(1)


@pytest.fixture
def make_user_in_workspace(db):
    """Create a User with a WorkspaceMembership in the given workspace.

    The RBACMiddleware reads ``request.workspace_membership`` from this row, so
    a membership is required for the composer view to render (otherwise 403).
    """

    def _make(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER, **kwargs):
        email = kwargs.pop("email", None) or f"compose-user-{next(_email_counter)}@example.com"
        user = User.objects.create_user(
            email=email,
            password="testpass123",
            name=kwargs.pop("name", "Compose User"),
            tos_accepted_at=timezone.now(),
        )
        WorkspaceMembership.objects.create(
            user=user,
            workspace=workspace,
            workspace_role=role,
        )
        return user

    return _make


@pytest.fixture
def make_post(db):
    """Create a Post in the given workspace.

    ``status`` is accepted for parity with the plan's call signature but is a
    derived, read-only property on Post (aggregated over PlatformPost children),
    so it is not written to the row.
    """

    def _make(workspace, status="draft", author=None, **kwargs):  # noqa: ARG001 - status kept for call-site parity
        kwargs.setdefault("caption", "Smoke-test caption")
        kwargs.setdefault("title", "Smoke-test title")
        return Post.objects.create(workspace=workspace, author=author, **kwargs)

    return _make
