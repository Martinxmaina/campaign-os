"""Ghost analytics — subscriber/member count from the Admin API.

All network is mocked (httpx) — no real Ghost calls. Mirrors the existing
provider test style in tests/test_ghost_provider.py.
"""
from __future__ import annotations

import datetime as dt

import httpx
from providers.ghost import GhostProvider
from providers.types import AccountMetrics

CREDS = {"admin_api_key": "id123:" + "ab" * 32, "base_url": "https://demo.ghost.io"}


def _provider():
    return GhostProvider(credentials=dict(CREDS))


def _range():
    now = dt.datetime(2026, 6, 14, 12, 0, 0)
    return (now, now)


def test_get_account_metrics_returns_member_total(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, **kw):
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        return httpx.Response(
            200,
            json={"members": [], "meta": {"pagination": {"total": 4231}}},
        )

    monkeypatch.setattr("providers.ghost.httpx.get", fake_get)
    metrics = _provider().get_account_metrics("unused", _range())

    assert isinstance(metrics, AccountMetrics)
    # followers=members per the plan's AccountMetrics shape.
    assert metrics.followers == 4231
    # also surfaced as a "subscribers" catalog metric.
    assert metrics.extra.get("subscribers") == 4231
    # Hit the members endpoint with a tiny page and the Ghost JWT header.
    assert "/ghost/api/admin/members/" in captured["url"]
    assert captured["headers"]["Authorization"].startswith("Ghost ")


def test_get_account_metrics_uses_limit_one(monkeypatch):
    """We only need the pagination total, so the page size must be 1
    (limit can be in the querystring or the params dict)."""
    captured = {}

    def fake_get(url, headers=None, params=None, **kw):
        captured["url"] = url
        captured["params"] = params
        return httpx.Response(200, json={"members": [], "meta": {"pagination": {"total": 1}}})

    monkeypatch.setattr("providers.ghost.httpx.get", fake_get)
    _provider().get_account_metrics("unused", _range())

    in_url = "limit=1" in captured["url"]
    in_params = bool(captured["params"]) and str(captured["params"].get("limit")) == "1"
    assert in_url or in_params


def test_get_account_metrics_missing_total_is_zero(monkeypatch):
    """No pagination block → no fabricated count, just zero followers."""
    monkeypatch.setattr(
        "providers.ghost.httpx.get",
        lambda url, headers=None, params=None, **kw: httpx.Response(200, json={"members": []}),
    )
    metrics = _provider().get_account_metrics("unused", _range())
    assert metrics.followers == 0


def test_get_account_metrics_raises_on_error(monkeypatch):
    import pytest
    from providers.exceptions import PublishError

    monkeypatch.setattr(
        "providers.ghost.httpx.get",
        lambda url, headers=None, params=None, **kw: httpx.Response(401, text="Unauthorized"),
    )
    with pytest.raises(PublishError):
        _provider().get_account_metrics("unused", _range())


def test_lifetime_total_not_replayed_into_history():
    """Ghost members total is a lifetime snapshot, not a per-day delta — the
    sync layer keys off this flag to avoid fabricating historical rows."""
    assert _provider().account_metrics_supports_date_range is False
