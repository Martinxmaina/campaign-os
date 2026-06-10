import pytest
import django
from django.utils import timezone

from apps.members.models import WorkspaceMembership, BUILTIN_ROLE_PERMISSIONS, PERMISSION_KEYS
from apps.members.services import WS_ROLE_LEVEL


def test_campaign_owner_can_approve():
    perms = BUILTIN_ROLE_PERMISSIONS["campaign_owner"]
    assert perms["approve_posts"] is True
    assert perms["create_posts"] is True

def test_principal_can_approve():
    perms = BUILTIN_ROLE_PERMISSIONS["principal"]
    assert perms["approve_posts"] is True

def test_pillar_lead_cannot_publish_directly():
    perms = BUILTIN_ROLE_PERMISSIONS["pillar_lead"]
    assert perms["publish_directly"] is False
    assert perms["create_posts"] is True
    assert perms["approve_posts"] is True

def test_member_cannot_approve():
    perms = BUILTIN_ROLE_PERMISSIONS["member"]
    assert perms["approve_posts"] is False
    assert perms["create_posts"] is True

def test_campaign_os_roles_in_choices():
    choices = dict(WorkspaceMembership.WorkspaceRole.choices)
    assert "campaign_owner" in choices
    assert "principal" in choices
    assert "pillar_lead" in choices
    assert "member" in choices


# ---------------------------------------------------------------------------
# New tests for Task 3 code-quality fixes
# ---------------------------------------------------------------------------

def test_all_workspace_roles_in_ws_role_level():
    """Every WorkspaceRole choice must have an entry in WS_ROLE_LEVEL.

    A missing role resolves to level 0 in services._inviter_workspace_level()
    and create_invitation(), causing ValueError('Unknown workspace role') for
    any invite/assignment that uses one of the new campaign-OS roles.
    """
    for role_value, _ in WorkspaceMembership.WorkspaceRole.choices:
        assert role_value in WS_ROLE_LEVEL, (
            f"WorkspaceRole '{role_value}' is missing from WS_ROLE_LEVEL in services.py. "
            "Invites/assignments with this role will raise ValueError."
        )


def test_new_roles_have_higher_level_than_viewer():
    """campaign_owner, principal, pillar_lead must outrank viewer and member."""
    viewer_level = WS_ROLE_LEVEL[WorkspaceMembership.WorkspaceRole.VIEWER]
    member_level = WS_ROLE_LEVEL[WorkspaceMembership.WorkspaceRole.MEMBER]
    for role in (
        WorkspaceMembership.WorkspaceRole.CAMPAIGN_OWNER,
        WorkspaceMembership.WorkspaceRole.PRINCIPAL,
        WorkspaceMembership.WorkspaceRole.PILLAR_LEAD,
    ):
        assert WS_ROLE_LEVEL[role] > viewer_level, f"{role} must outrank viewer"
        assert WS_ROLE_LEVEL[role] > member_level, f"{role} must outrank member"


def test_campaign_owner_level_below_owner():
    """campaign_owner must be subordinate to workspace owner and admin."""
    owner_level = WS_ROLE_LEVEL[WorkspaceMembership.WorkspaceRole.OWNER]
    admin_level = WS_ROLE_LEVEL[WorkspaceMembership.WorkspaceRole.ADMIN]
    co_level = WS_ROLE_LEVEL[WorkspaceMembership.WorkspaceRole.CAMPAIGN_OWNER]
    assert co_level < owner_level
    assert co_level < admin_level


def test_role_hierarchy_ordering():
    """Strict ordering: owner > admin > campaign_owner > principal > pillar_lead > manager."""
    r = WorkspaceMembership.WorkspaceRole
    assert WS_ROLE_LEVEL[r.OWNER] > WS_ROLE_LEVEL[r.ADMIN]
    assert WS_ROLE_LEVEL[r.ADMIN] > WS_ROLE_LEVEL[r.CAMPAIGN_OWNER]
    assert WS_ROLE_LEVEL[r.CAMPAIGN_OWNER] > WS_ROLE_LEVEL[r.PRINCIPAL]
    assert WS_ROLE_LEVEL[r.PRINCIPAL] > WS_ROLE_LEVEL[r.PILLAR_LEAD]
    assert WS_ROLE_LEVEL[r.PILLAR_LEAD] > WS_ROLE_LEVEL[r.MANAGER]
    assert WS_ROLE_LEVEL[r.MANAGER] > WS_ROLE_LEVEL[r.VIEWER]


def test_campaign_owner_permissions_identical_to_owner_is_intentional():
    """campaign_owner must have ALL permissions — same as owner.

    This is deliberate: campaign_owner has full authority within their
    campaign-scoped workspace. If this equality is ever broken intentionally,
    this test must be updated with a comment explaining the divergence.
    """
    owner_perms = BUILTIN_ROLE_PERMISSIONS["owner"]
    co_perms = BUILTIN_ROLE_PERMISSIONS["campaign_owner"]
    assert owner_perms == co_perms, (
        "campaign_owner permissions diverged from owner unexpectedly. "
        "If this is intentional, update test_campaign_owner_permissions_identical_to_owner_is_intentional "
        "with an explanation."
    )


def test_campaign_owner_is_not_a_privilege_escalation_vs_owner_level():
    """campaign_owner role level must be strictly less than owner level.

    Even though campaign_owner has the same permission set, it cannot be
    granted by a campaign_owner (level < owner level), preventing lateral
    promotion of the top-tier role.
    """
    assert WS_ROLE_LEVEL[WorkspaceMembership.WorkspaceRole.CAMPAIGN_OWNER] < WS_ROLE_LEVEL[
        WorkspaceMembership.WorkspaceRole.OWNER
    ]


@pytest.mark.django_db
def test_pillar_field_only_allowed_for_pillar_lead_role():
    """Setting pillar on a non-pillar_lead membership must raise ValidationError."""
    from django.core.exceptions import ValidationError
    from apps.accounts.models import User
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace
    from apps.members.models import OrgMembership

    user = User.objects.create_user(
        email="pillar_test@example.com",
        password="testpass123",
        tos_accepted_at=timezone.now(),
    )
    # Clear auto-provisioned org/workspace
    auto_org_ids = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_org_ids).delete()

    org = Organization.objects.create(name="Test Org")
    ws = Workspace.objects.create(organization=org, name="Test WS")

    # pillar_lead with pillar set — OK
    m = WorkspaceMembership(
        user=user,
        workspace=ws,
        workspace_role=WorkspaceMembership.WorkspaceRole.PILLAR_LEAD,
        pillar="energy",
    )
    m.save()  # must not raise

    # Change role to viewer but keep stale pillar — must raise
    m.workspace_role = WorkspaceMembership.WorkspaceRole.VIEWER
    with pytest.raises(ValidationError, match="pillar.*pillar_lead"):
        m.save()


@pytest.mark.django_db
def test_role_change_from_pillar_lead_clears_pillar_on_explicit_clear():
    """Clearing pillar before saving a role change succeeds."""
    from django.core.exceptions import ValidationError
    from apps.accounts.models import User
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace
    from apps.members.models import OrgMembership

    user = User.objects.create_user(
        email="clear_pillar@example.com",
        password="testpass123",
        tos_accepted_at=timezone.now(),
    )
    auto_org_ids = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_org_ids).delete()

    org = Organization.objects.create(name="Test Org 2")
    ws = Workspace.objects.create(organization=org, name="Test WS 2")

    m = WorkspaceMembership.objects.create(
        user=user,
        workspace=ws,
        workspace_role=WorkspaceMembership.WorkspaceRole.PILLAR_LEAD,
        pillar="climate",
    )
    m.refresh_from_db()
    assert m.pillar == "climate"

    # Clear pillar then change role — must succeed
    m.pillar = ""
    m.workspace_role = WorkspaceMembership.WorkspaceRole.EDITOR
    m.save()  # must not raise
    m.refresh_from_db()
    assert m.workspace_role == WorkspaceMembership.WorkspaceRole.EDITOR
    assert m.pillar == ""
