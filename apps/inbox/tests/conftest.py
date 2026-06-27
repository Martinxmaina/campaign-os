import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import WorkspaceMembership


@pytest.fixture
def make_user_in_workspace(db):
    """Create a User with a WorkspaceMembership at the given role.

    Mirrors the project's existing workspace-membership setup (see
    apps/approvals/tests/test_ai_approvals_queue.py): the RBAC middleware
    resolves the membership from the URL ``workspace_id`` and
    ``require_permission`` reads ``effective_permissions``.
    """
    counter = {"n": 0}

    def _make(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER):
        counter["n"] += 1
        user = User.objects.create_user(
            email=f"member{counter['n']}@example.com",
            password="testpass123",
            name=f"Member {counter['n']}",
            tos_accepted_at=timezone.now(),
        )
        WorkspaceMembership.objects.create(
            user=user, workspace=workspace, workspace_role=role
        )
        user.last_workspace_id = workspace.id
        user.save(update_fields=["last_workspace_id"])
        return user

    return _make
