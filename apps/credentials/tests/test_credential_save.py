import pytest
from django.urls import reverse

from apps.credentials.models import PlatformCredential


@pytest.fixture
def admin_client(client, org_owner):
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_save_credential_marks_configured(admin_client):
    # The credential is saved under the org the RBAC middleware resolves for the
    # logged-in user (request.org). Assert on the saved credential directly rather
    # than pinning to a specific fixture org — the test user can have >1 membership.
    url = reverse("credentials:save", args=["linkedin_personal"])
    resp = admin_client.post(url, {"client_id": "abc123", "client_secret": "sek456"})
    assert resp.status_code in (302, 200)
    cred = PlatformCredential.objects.get(platform="linkedin_personal", is_configured=True)
    assert cred.credentials["client_id"] == "abc123"
    assert cred.credentials["client_secret"] == "sek456"


@pytest.mark.django_db
def test_save_requires_both_fields(admin_client, organization):
    url = reverse("credentials:save", args=["twitter"])
    admin_client.post(url, {"client_id": "only_id"})
    assert not PlatformCredential.objects.filter(
        organization=organization, platform="twitter", is_configured=True
    ).exists()


@pytest.mark.django_db
def test_ghost_configured_via_env_shows_connect_button(admin_client, settings):
    """An env-provided Ghost key (GHOST_ADMIN_API_KEY) makes the card show as
    configured so the 'Connect Ghost' button appears — no DB row / re-entry needed."""
    settings.PLATFORM_CREDENTIALS_FROM_ENV = {
        "ghost": {"admin_api_key": "id:secret", "base_url": "https://x.ghost.io"}
    }
    resp = admin_client.get(reverse("credentials:list"))
    assert resp.status_code == 200
    assert b"Connect Ghost" in resp.content


@pytest.mark.django_db
def test_resolve_credentials_prefers_db_then_env(organization, settings):
    """_resolve_credentials returns the DB row when present, else the env fallback."""
    from apps.credentials.views import _resolve_credentials

    settings.PLATFORM_CREDENTIALS_FROM_ENV = {
        "ghost": {"admin_api_key": "env-id:envsecret", "base_url": "https://env.ghost.io"}
    }
    # No DB row → env fallback
    assert _resolve_credentials(organization, "ghost")["admin_api_key"] == "env-id:envsecret"

    # DB row wins over env
    PlatformCredential.objects.create(
        organization=organization, platform="ghost",
        credentials={"admin_api_key": "db-id:dbsecret", "base_url": "https://db.ghost.io"},
        is_configured=True,
    )
    assert _resolve_credentials(organization, "ghost")["admin_api_key"] == "db-id:dbsecret"


@pytest.mark.django_db
def test_non_admin_cannot_save(client, user, organization):
    from apps.members.models import OrgMembership
    OrgMembership.objects.create(user=user, organization=organization, org_role="member")
    client.force_login(user)
    url = reverse("credentials:save", args=["linkedin_personal"])
    client.post(url, {"client_id": "x", "client_secret": "y"})
    assert not PlatformCredential.objects.filter(
        organization=organization, platform="linkedin_personal"
    ).exists()
