# apps/credentials/tests/test_account_hub.py
import pytest
from apps.credentials.account_hub import accounts_by_platform


@pytest.mark.django_db
def test_groups_accounts_by_platform_across_houses(organization):
    from apps.workspaces.models import Workspace
    from apps.social_accounts.models import SocialAccount
    ws1 = Workspace.objects.create(organization=organization, name="WAIIS")
    ws2 = Workspace.objects.create(organization=organization, name="AfCEN")
    SocialAccount.objects.create(workspace=ws1, platform="linkedin_personal",
        account_platform_id="li-1", account_name="Martin")
    SocialAccount.objects.create(workspace=ws2, platform="linkedin_personal",
        account_platform_id="li-2", account_name="Joseph")
    SocialAccount.objects.create(workspace=ws1, platform="twitter",
        account_platform_id="tw-1", account_name="WAIIS X")

    out = accounts_by_platform(organization)
    assert set(out.keys()) == {"linkedin_personal", "twitter"}
    li = out["linkedin_personal"]
    assert len(li) == 2                                  # two LinkedIn accounts
    houses = {row["house"] for row in li}
    assert houses == {"WAIIS", "AfCEN"}                  # labelled by house
    assert all("workspace_id" in row and "account" in row for row in li)


@pytest.mark.django_db
def test_empty_org_returns_empty(organization):
    assert accounts_by_platform(organization) == {}


@pytest.mark.django_db
def test_credentials_list_context_has_accounts_and_houses(client, org_owner, organization):
    from apps.workspaces.models import Workspace
    from apps.social_accounts.models import SocialAccount
    from django.urls import reverse
    ws = Workspace.objects.create(organization=organization, name="WAIIS")
    SocialAccount.objects.create(workspace=ws, platform="linkedin_personal",
        account_platform_id="li-9", account_name="Martin")
    client.force_login(org_owner)
    resp = client.get(reverse("credentials:list"))
    assert resp.status_code == 200
    # The page lists the connected account + its house.
    assert b"Martin" in resp.content
    assert b"WAIIS" in resp.content
