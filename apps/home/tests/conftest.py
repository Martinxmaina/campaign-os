"""Shared fixtures for the role-aware Home tests.

``make_user_in_workspace`` builds a User whose ONLY workspace membership is the
requested role. The signup ``post_save`` signal
(``apps.accounts.signals.provision_organization_and_workspace``) auto-grants
every new user an OWNER OrgMembership + OWNER WorkspaceMembership in the seeded
org/workspace, so — exactly like ``apps/joseph/tests/test_home.py``'s ``viewer``
fixture — we strip those auto-granted rows first, then attach the user to the
test's ``workspace`` with the role under test.
"""
import itertools

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership

_email_counter = itertools.count(1)


@pytest.fixture
def social_account(db, workspace):
    """A connected SocialAccount in the test workspace.

    Modeled on ``apps/approvals/tests/conftest.py`` + the real
    ``apps.social_accounts.models.SocialAccount`` fields.
    """
    from apps.social_accounts.models import SocialAccount

    return SocialAccount.objects.create(
        workspace=workspace,
        platform="linkedin",
        account_platform_id="acct-linkedin-home",
        account_name="LinkedIn account",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )


@pytest.fixture
def make_post(db):
    """Build a ``composer.Post`` in a workspace.

    ``Post.status`` is a *derived* property over ``platform_posts`` (see
    ``apps.composer.status.derive_post_status``) — it is NOT a settable field —
    so the ``status`` kwarg here is only a hint; callers that need a specific
    derived status attach ``PlatformPost`` children themselves (as the A2
    published-post test does). ``scheduled_at`` is a real Post field; ``author``
    maps to ``Post.author``.
    """
    from apps.composer.models import Post

    def _make(workspace, status="draft", author=None, scheduled_at=None, **kwargs):
        return Post.objects.create(
            workspace=workspace,
            author=author,
            caption=kwargs.pop("caption", "Sample caption"),
            title=kwargs.pop("title", "Sample title"),
            scheduled_at=scheduled_at,
            **kwargs,
        )

    return _make


@pytest.fixture
def make_user_in_workspace(db):
    def _make(workspace, role=WorkspaceMembership.WorkspaceRole.MEMBER):
        n = next(_email_counter)
        user = User.objects.create_user(
            email=f"home-user-{n}@example.com",
            password="testpass123",
            name=f"Home User {n}",
            tos_accepted_at=timezone.now(),
        )
        # Strip the singleton-owner memberships the signup signal auto-granted,
        # so this user's only workspace role is the one under test.
        WorkspaceMembership.objects.filter(user=user).delete()
        OrgMembership.objects.filter(user=user).delete()
        OrgMembership.objects.create(
            user=user,
            organization=workspace.organization,
            org_role=OrgMembership.OrgRole.MEMBER,
        )
        WorkspaceMembership.objects.create(
            user=user, workspace=workspace, workspace_role=role
        )
        user.last_workspace_id = workspace.id
        user.save(update_fields=["last_workspace_id"])
        return user

    return _make
