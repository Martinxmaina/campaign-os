"""Thin Blotato account-discovery client for the import flow."""
from __future__ import annotations

import httpx
from django.conf import settings


def _base() -> str:
    return getattr(settings, "BLOTATO_API_BASE", "https://backend.blotato.com/v2").rstrip("/")


def _api_key(organization_id) -> str:
    from apps.credentials.models import PlatformCredential
    try:
        cred = PlatformCredential.objects.for_org(organization_id).get(
            platform="blotato", is_configured=True)
        key = cred.credentials.get("api_key", "")
        if key:
            return key
    except PlatformCredential.DoesNotExist:
        pass
    return getattr(settings, "BLOTATO_API_KEY", "")


def blotato_list_accounts(organization_id) -> list[dict]:
    key = _api_key(organization_id)
    if not key:
        return []
    with httpx.Client(timeout=15.0) as c:
        r = c.get(f"{_base()}/users/me/accounts", headers={"blotato-api-key": key})
        r.raise_for_status()
        return r.json().get("items", [])


def blotato_subaccount_page_id(organization_id, account_id) -> str:
    key = _api_key(organization_id)
    if not key:
        return ""
    with httpx.Client(timeout=15.0) as c:
        r = c.get(f"{_base()}/users/me/accounts/{account_id}/subaccounts",
                  headers={"blotato-api-key": key})
        if r.status_code != 200:
            return ""
        items = r.json().get("items", [])
        return str(items[0].get("pageId")) if items else ""
