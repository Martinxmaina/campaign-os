"""LinkedIn Company follower analytics — networkSizes follower count.

All network is mocked (httpx via the base ``_request`` -> httpx.Client) — no
real LinkedIn calls. Mirrors the existing provider test style under
tests/providers/.
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
from providers.exceptions import APIError, PublishError
from providers.linkedin import API_BASE
from providers.linkedin_company import LinkedInCompanyProvider
from providers.types import AccountMetrics

# The analytics sync injects the connected account's org id into the provider
# credentials (account_platform_id) so the lifetime follower count can be read.
CREDS = {
    "client_id": "cid",
    "client_secret": "csecret",
    "account_platform_id": "98765",
}


def _provider(**overrides):
    creds = {**CREDS, **overrides}
    return LinkedInCompanyProvider(credentials=creds)


def _range():
    now = dt.datetime(2026, 6, 14, 12, 0, 0)
    return (now, now)


def _patch_request(monkeypatch, response: httpx.Response):
    captured: dict = {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = kwargs.get("headers") or {}
            captured["params"] = kwargs.get("params")
            return response

    monkeypatch.setattr("providers.base.httpx.Client", _FakeClient)
    return captured


def test_get_account_metrics_returns_followers(monkeypatch):
    captured = _patch_request(
        monkeypatch,
        httpx.Response(200, json={"firstDegreeSize": 8421, "secondDegreeSize": 0}),
    )

    metrics = _provider().get_account_metrics("token-abc", _range())

    assert isinstance(metrics, AccountMetrics)
    # firstDegreeSize -> followers per the plan's AccountMetrics shape.
    assert metrics.followers == 8421

    # Hit the networkSizes endpoint for the org URN with the right edgeType.
    assert captured["method"] == "GET"
    assert f"{API_BASE}/rest/networkSizes/" in captured["url"]
    assert "urn%3Ali%3Aorganization%3A98765" in captured["url"]
    assert captured["params"]["edgeType"] == "COMPANY_FOLLOWED_BY_MEMBER"
    # Versioned REST headers + bearer auth (reused from the publish path).
    assert captured["headers"]["LinkedIn-Version"]
    assert captured["headers"]["X-Restli-Protocol-Version"] == "2.0.0"
    assert captured["headers"]["Authorization"] == "Bearer token-abc"


def test_missing_first_degree_size_is_zero(monkeypatch):
    """No firstDegreeSize -> no fabricated count, just zero followers."""
    _patch_request(monkeypatch, httpx.Response(200, json={"secondDegreeSize": 5}))
    metrics = _provider().get_account_metrics("token-abc", _range())
    assert metrics.followers == 0


def test_insufficient_scope_raises_scope_error(monkeypatch):
    """403 (token lacks r_organization_social / rw_organization_admin) must
    raise an error the sync recognizes as insufficient-scope, so the account is
    flagged analytics_needs_reconnect — NOT a hard crash."""
    from apps.analytics.tasks import _is_insufficient_scope

    _patch_request(
        monkeypatch,
        httpx.Response(403, text="Not enough permissions to access organization"),
    )

    with pytest.raises(PublishError) as exc_info:
        _provider().get_account_metrics("token-abc", _range())

    assert _is_insufficient_scope(exc_info.value)


def test_no_org_id_raises_clearly(monkeypatch):
    """Without an org URN there is nothing to query — fail loudly, don't guess."""
    _patch_request(monkeypatch, httpx.Response(200, json={"firstDegreeSize": 1}))
    provider = LinkedInCompanyProvider(credentials={"client_id": "x"})
    with pytest.raises(PublishError):
        provider.get_account_metrics("token-abc", _range())


def test_lifetime_total_not_replayed_into_history():
    """Follower count is a lifetime snapshot, not a per-day delta — the sync
    layer keys off this flag to avoid fabricating historical rows."""
    assert _provider().account_metrics_supports_date_range is False
