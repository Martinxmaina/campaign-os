"""Shared fixtures for composer view tests.

Provides factory fixtures used by the compose-page render smoke tests:

- ``make_user_in_workspace`` — create a User with an Org + Workspace membership
  at a given workspace role (defaults to MANAGER, which has ``create_posts``).
- ``make_post`` — create a Post in a workspace (for the compose_edit view).
"""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


@pytest.fixture
def make_user_in_workspace(db):
    """Factory: a User who is a member of a (new) Org + Workspace.

    Returns a tuple ``(user, workspace)``. The workspace role defaults to
    MANAGER (which carries the ``create_posts`` permission the compose view
    requires).
    """
    _counter = {"n": 0}

    def _make(workspace_role=WorkspaceMembership.WorkspaceRole.MANAGER, workspace=None):
        _counter["n"] += 1
        n = _counter["n"]
        user = User.objects.create_user(
            email=f"composer-user-{n}@example.com",
            password="testpass123",
            tos_accepted_at=timezone.now(),
        )
        if workspace is None:
            org = Organization.objects.create(name=f"Test Org {n}")
            workspace = Workspace.objects.create(organization=org, name=f"Test Workspace {n}")
        else:
            org = workspace.organization
        OrgMembership.objects.create(
            user=user,
            organization=org,
            org_role=OrgMembership.OrgRole.MEMBER,
        )
        WorkspaceMembership.objects.create(
            user=user,
            workspace=workspace,
            workspace_role=workspace_role,
        )
        return user, workspace

    return _make


@pytest.fixture
def make_post(db):
    """Factory: a Post in the given workspace."""

    def _make(workspace, author=None, **kwargs):
        defaults = {
            "workspace": workspace,
            "author": author,
            "title": "Smoke title",
            "caption": "Smoke caption",
        }
        defaults.update(kwargs)
        return Post.objects.create(**defaults)

    return _make
