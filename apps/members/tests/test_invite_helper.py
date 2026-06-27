"""Task A8: per-role helper text on the invite form.

The member list (``members:list``) renders the invite modal, whose per-workspace
role <select> now carries a one-line helper describing what each role tier can
do (drawn from spec §3.3.1) so an org admin can pick the right role without
guessing.

We build the org-admin user inline, modeled on
``apps/members/tests/test_role_hierarchy.py``'s ``_make_user`` helper: the
accounts signup signal auto-provisions a default Org/Workspace/OrgMembership for
every new User, so we strip those rows and attach the user to the test
``workspace``'s org as an admin, ensuring ``request.org`` resolves to that org
(and ``org_workspaces`` is non-empty, so the per-role helper inside the
``{% for ws in org_workspaces %}`` loop actually renders).
"""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def org_admin_user(db, workspace):
    user = User.objects.create_user(
        email="org-admin@example.com",
        password="testpass123",
        name="Org Admin",
        tos_accepted_at=timezone.now(),
    )
    # Strip the singleton org/workspace memberships the signup signal granted,
    # then attach the user to the TEST workspace's org as an admin so the RBAC
    # middleware resolves request.org to that org (which has `workspace`).
    from apps.members.models import WorkspaceMembership

    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    OrgMembership.objects.create(
        user=user,
        organization=workspace.organization,
        org_role=OrgMembership.OrgRole.ADMIN,
    )
    return user


def test_member_list_renders_role_helper(client, org_admin_user, workspace):
    client.force_login(org_admin_user)
    resp = client.get(reverse("members:list"))
    assert resp.status_code == 200
    assert b"CRM + publishing" in resp.content  # helper text for campaign_owner tier
