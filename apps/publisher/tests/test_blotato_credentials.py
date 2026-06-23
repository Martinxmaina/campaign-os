# apps/publisher/tests/test_blotato_credentials.py
import pytest
from django.test import override_settings


@pytest.fixture
def account(db):
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    return SocialAccount.objects.create(
        workspace=ws, platform="blotato_instagram",
        account_platform_id="98432", account_name="AfCEN")


@pytest.mark.django_db
@override_settings(BLOTATO_API_KEY="env-key-123")
def test_blotato_credentials_fall_back_to_env(account):
    from apps.publisher.engine import _resolve_publish_credentials
    creds = _resolve_publish_credentials(account)
    assert creds == {"api_key": "env-key-123"}


@pytest.mark.django_db
def test_blotato_credentials_prefer_platform_credential(account):
    from apps.credentials.models import PlatformCredential
    from apps.publisher.engine import _resolve_publish_credentials
    PlatformCredential.objects.create(
        organization=account.workspace.organization, platform="blotato",
        credentials={"api_key": "org-key-999"}, is_configured=True)
    creds = _resolve_publish_credentials(account)
    assert creds == {"api_key": "org-key-999"}
