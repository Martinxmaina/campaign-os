# apps/publisher/tests/test_blotato_extras.py
import pytest


def _make(db_platform, provider_config):
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    return SocialAccount.objects.create(
        workspace=ws, platform=db_platform, account_platform_id="98432",
        account_name="AfCEN", provider_config=provider_config)


@pytest.mark.django_db
def test_blotato_extras_injects_account_id_and_page_id():
    from apps.publisher.engine import _blotato_extra
    acct = _make("blotato_facebook", {"blotato_account_id": "98432", "page_id": "PAGE7"})
    extra = {}
    _blotato_extra(acct, "blotato_facebook", extra)
    assert extra["blotato_account_id"] == "98432"
    assert extra["page_id"] == "PAGE7"


@pytest.mark.django_db
def test_blotato_extras_account_id_falls_back_to_platform_id():
    from apps.publisher.engine import _blotato_extra
    acct = _make("blotato_instagram", {})
    extra = {}
    _blotato_extra(acct, "blotato_instagram", extra)
    assert extra["blotato_account_id"] == "98432"
    assert "page_id" not in extra
