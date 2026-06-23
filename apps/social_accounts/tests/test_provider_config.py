import pytest


@pytest.fixture
def workspace(db):
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    return Workspace.objects.create(organization=org, name="WAIIS")


@pytest.mark.django_db
def test_provider_config_defaults_to_empty_dict(workspace):
    from apps.social_accounts.models import SocialAccount
    acct = SocialAccount.objects.create(
        workspace=workspace, platform="blotato_instagram",
        account_platform_id="98432", account_name="AfCEN",
    )
    acct.refresh_from_db()
    assert acct.provider_config == {}
    acct.provider_config = {"blotato_account_id": "98432", "page_id": "777"}
    acct.save(update_fields=["provider_config"])
    acct.refresh_from_db()
    assert acct.provider_config["page_id"] == "777"
