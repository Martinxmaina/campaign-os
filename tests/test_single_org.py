import pytest
from django.urls import reverse, NoReverseMatch


@pytest.mark.django_db
def test_default_org_and_workspace_seeded():
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace
    assert Organization.objects.count() == 1
    assert Workspace.objects.count() >= 1


@pytest.mark.django_db
def test_signup_provisioning_attaches_to_singleton_not_new_org():
    """FIX E: provisioning a user must attach them to the AfCEN/WAIIS
    singleton (matching the Task 12 seed) — never create a per-user org.
    Exactly one Organization must exist after multiple signups."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.accounts.signals import (
        SINGLETON_ORG_NAME,
        SINGLETON_WORKSPACE_NAME,
        provision_organization_and_workspace,
    )
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace

    # post_save already provisions on create, so two users should both land
    # in the one singleton org.
    u1 = User.objects.create_user(
        email="one@example.com", password="x", tos_accepted_at=timezone.now()
    )
    u2 = User.objects.create_user(
        email="two@example.com", password="x", tos_accepted_at=timezone.now()
    )

    # Idempotent re-call must not create duplicates.
    provision_organization_and_workspace(u1)

    assert Organization.objects.count() == 1
    org = Organization.objects.get()
    assert org.name == SINGLETON_ORG_NAME

    ws = Workspace.objects.filter(organization=org, name=SINGLETON_WORKSPACE_NAME)
    assert ws.count() == 1

    assert OrgMembership.objects.filter(user=u1, organization=org).count() == 1
    assert OrgMembership.objects.filter(user=u2, organization=org).count() == 1
    assert WorkspaceMembership.objects.filter(user=u1, workspace=ws.get()).exists()
    assert WorkspaceMembership.objects.filter(user=u2, workspace=ws.get()).exists()


def test_billing_and_client_portal_routes_removed():
    for name in ["client_portal:index", "intelligence:checkout"]:
        with pytest.raises(NoReverseMatch):
            reverse(name)
