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
def test_non_admin_cannot_save(client, user, organization):
    from apps.members.models import OrgMembership
    OrgMembership.objects.create(user=user, organization=organization, org_role="member")
    client.force_login(user)
    url = reverse("credentials:save", args=["linkedin_personal"])
    client.post(url, {"client_id": "x", "client_secret": "y"})
    assert not PlatformCredential.objects.filter(
        organization=organization, platform="linkedin_personal"
    ).exists()
