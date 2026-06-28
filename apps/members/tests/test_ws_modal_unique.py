"""Workspace-assignment modal ids must be UNIQUE per member.

Each member row teleports its own "Manage Workspaces" modal containing a
hx-target div. Before the fix every row used id="ws-modal-content", so with >1
member the duplicate ids made htmx load the form into the FIRST row's modal —
the clicked member's modal stayed empty ("can't assign workspaces"). Now the id
is suffixed with the membership id.
"""
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership

pytestmark = pytest.mark.django_db


def _strip(user):
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()


@pytest.fixture
def org_admin(db, workspace):
    u = User.objects.create_user(email="adm@example.com", password="x", name="Adm", tos_accepted_at=timezone.now())
    _strip(u)
    OrgMembership.objects.create(user=u, organization=workspace.organization, org_role=OrgMembership.OrgRole.ADMIN)
    return u


def test_ws_modal_content_ids_are_unique(client, org_admin, workspace):
    org = workspace.organization
    for i in range(2):
        m = User.objects.create_user(email=f"m{i}@example.com", password="x", name=f"M{i}", tos_accepted_at=timezone.now())
        _strip(m)
        OrgMembership.objects.create(user=m, organization=org, org_role=OrgMembership.OrgRole.MEMBER)

    client.force_login(org_admin)
    body = client.get(reverse("members:list")).content.decode()

    assert 'id="ws-modal-content"' not in body          # no bare duplicate id
    assert body.count('id="ws-modal-content-') >= 2      # one unique target per member
