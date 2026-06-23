# apps/social_accounts/tests/test_blotato_import.py
from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.fixture
def authed(client, db):
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace
    # NOTE: a post_save signal auto-provisions the singleton "AfCEN" org on user
    # creation, so use a distinct org name here to avoid the get_or_create
    # collision that yields MultipleObjectsReturned.
    org = Organization.objects.create(name="AfCEN Blotato Test")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    u = User.objects.create_user(email="a@x.io", password="pw", name="A",
                                 tos_accepted_at=timezone.now())
    OrgMembership.objects.create(user=u, organization=org, org_role=OrgMembership.OrgRole.OWNER)
    WorkspaceMembership.objects.create(user=u, workspace=ws, workspace_role="owner")
    u.last_workspace_id = ws.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return client, ws


ACCOUNTS = {"items": [
    {"id": "111", "platform": "instagram", "fullname": "AfCEN IG", "username": "afcen"},
    {"id": "222", "platform": "facebook", "fullname": "AfCEN FB", "username": "afcenfb"},
    {"id": "333", "platform": "tiktok", "fullname": "AfCEN TT", "username": "afcentt"},
]}


@pytest.mark.django_db
def test_import_lists_supported_accounts(authed):
    client, ws = authed
    with patch("apps.social_accounts.views.blotato_list_accounts", return_value=ACCOUNTS["items"]):
        resp = client.get(reverse("social_accounts:blotato_import", args=[ws.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "AfCEN IG" in body and "AfCEN FB" in body
    # tiktok is out of MVP scope -> shown disabled / not importable
    assert "AfCEN TT" not in body or "not yet supported" in body.lower()


@pytest.mark.django_db
def test_import_creates_social_accounts_with_pageid(authed):
    client, ws = authed
    from apps.social_accounts.models import SocialAccount
    with patch("apps.social_accounts.views.blotato_list_accounts", return_value=ACCOUNTS["items"]), \
         patch("apps.social_accounts.views.blotato_subaccount_page_id", return_value="PAGE_X"):
        resp = client.post(reverse("social_accounts:blotato_import", args=[ws.id]),
                           {"account_id": ["111", "222"]})
    assert resp.status_code in (302, 200)
    ig = SocialAccount.objects.get(workspace=ws, platform="blotato_instagram")
    assert ig.account_platform_id == "111"
    assert ig.provider_config["blotato_account_id"] == "111"
    fb = SocialAccount.objects.get(workspace=ws, platform="blotato_facebook")
    assert fb.provider_config["page_id"] == "PAGE_X"
