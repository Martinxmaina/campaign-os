import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_connect_ghost_creates_single_account(client, org_owner, monkeypatch):
    from apps.members.models import OrgMembership
    from apps.credentials.models import PlatformCredential
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    from providers.types import AccountProfile
    # Use the org the RBAC middleware will actually resolve for this user
    # (the test user can hold more than one membership), so the view's
    # org-scoped credential/workspace lookups line up with our setup.
    org = OrgMembership.objects.filter(user=org_owner).first().organization
    Workspace.objects.create(name="Main", organization=org)
    PlatformCredential.objects.create(organization=org, platform="ghost",
        credentials={"admin_api_key": "a:bb", "base_url": "https://demo.ghost.io"}, is_configured=True)
    monkeypatch.setattr("providers.ghost.GhostProvider.get_profile",
        lambda self, t="": AccountProfile(platform_id="demo.ghost.io", name="Nexus Brief"))
    client.force_login(org_owner)
    resp = client.post(reverse("credentials:connect-ghost"))
    assert resp.status_code in (302, 200)
    qs = SocialAccount.objects.filter(platform="ghost", workspace__organization=org)
    assert qs.count() == 1
    assert qs.first().account_name == "Nexus Brief"
    # idempotent
    client.post(reverse("credentials:connect-ghost"))
    assert qs.count() == 1
