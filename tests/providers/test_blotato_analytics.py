"""Blotato post-analytics tests.

Verifies that BlotatoProvider.get_post_metrics() calls
GET /v2/posts/{id}/analytics and maps the string metric values to the correct
PostMetrics fields. All network is mocked via monkeypatch on _request so no
real HTTP calls are made.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from providers.blotato import BlotatoInstagramProvider, BlotatoProvider
from providers.types import AccountMetrics, PostMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resp(json_data, status=200):
    r = MagicMock()
    r.json.return_value = json_data
    r.status_code = status
    return r


def _provider(subclass=BlotatoInstagramProvider):
    return subclass({"api_key": "test-key"})


# ---------------------------------------------------------------------------
# get_post_metrics — happy path
# ---------------------------------------------------------------------------

def test_get_post_metrics_maps_all_fields(monkeypatch):
    """All known metric keys arrive as strings and are coerced to int."""
    p = _provider()
    captured = {}

    def fake_request(method, url, **kw):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kw.get("headers", {})
        return _resp({
            "publishedPostId": "post-42",
            "platform": "instagram",
            "lastFetchedAt": "2026-06-25T12:00:00Z",
            "lastError": None,
            "metrics": {
                "impressionsCount": "1234",
                "reachCount": "987",
                "likesCount": "55",
                "commentsCount": "12",
                "sharesCount": "7",
                "savesCount": "30",
                "viewsCount": "2000",
                "clicksCount": "88",
                "repliesCount": "3",
                "followsCount": "5",
                "interactionsSum": "120",
            },
        })

    monkeypatch.setattr(p, "_request", fake_request)
    metrics = p.get_post_metrics("unused-token", "post-42")

    assert isinstance(metrics, PostMetrics)
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/posts/post-42/analytics")
    assert captured["headers"].get("blotato-api-key") == "test-key"

    assert metrics.impressions == 1234
    assert metrics.reach == 987
    assert metrics.likes == 55
    assert metrics.comments == 12
    assert metrics.shares == 7
    assert metrics.saves == 30
    assert metrics.video_views == 2000
    assert metrics.clicks == 88
    assert metrics.extra["replies"] == 3
    assert metrics.extra["follows"] == 5


def test_get_post_metrics_missing_keys_default_to_zero(monkeypatch):
    """Absent metric keys produce 0 rather than raising."""
    p = _provider()
    monkeypatch.setattr(p, "_request", lambda *a, **kw: _resp({"metrics": {}}))

    metrics = p.get_post_metrics("tok", "post-0")
    assert metrics.impressions == 0
    assert metrics.likes == 0
    assert metrics.reach == 0
    assert metrics.video_views == 0
    assert metrics.clicks == 0


def test_get_post_metrics_null_metrics_key_defaults_to_zero(monkeypatch):
    """API responds with ``"metrics": null`` — should not raise."""
    p = _provider()
    monkeypatch.setattr(p, "_request", lambda *a, **kw: _resp({"metrics": None}))

    metrics = p.get_post_metrics("tok", "post-null")
    assert metrics.impressions == 0
    assert metrics.likes == 0


def test_get_post_metrics_non_numeric_string_defaults_to_zero(monkeypatch):
    """Non-numeric values (e.g. 'n/a') should not raise and default to 0."""
    p = _provider()
    monkeypatch.setattr(
        p,
        "_request",
        lambda *a, **kw: _resp({"metrics": {"likesCount": "n/a", "impressionsCount": ""}}),
    )
    metrics = p.get_post_metrics("tok", "post-bad")
    assert metrics.likes == 0
    assert metrics.impressions == 0


def test_get_post_metrics_numeric_int_values(monkeypatch):
    """API may return integers (not strings) — should work without coercion issues."""
    p = _provider()
    monkeypatch.setattr(
        p,
        "_request",
        lambda *a, **kw: _resp({"metrics": {"likesCount": 42, "viewsCount": 999}}),
    )
    metrics = p.get_post_metrics("tok", "post-int")
    assert metrics.likes == 42
    assert metrics.video_views == 999


def test_get_post_metrics_uses_api_base_url(monkeypatch):
    """URL must begin with the configured BLOTATO_API_BASE."""
    import providers.blotato as blotato_module

    p = _provider()
    captured_url = {}
    monkeypatch.setattr(p, "_request", lambda m, u, **kw: (captured_url.update({"url": u}), _resp({}))[1])
    monkeypatch.setattr(blotato_module, "_api_base", lambda: "https://backend.blotato.com/v2")

    p.get_post_metrics("tok", "post-99")
    assert captured_url["url"] == "https://backend.blotato.com/v2/posts/post-99/analytics"


# ---------------------------------------------------------------------------
# All blotato_* subclasses inherit get_post_metrics
# ---------------------------------------------------------------------------

def test_all_blotato_subclasses_inherit_analytics():
    """Every blotato_* subclass gets get_post_metrics from BlotatoProvider."""
    from providers.blotato import (
        BlotatoBlueskyProvider,
        BlotatoFacebookProvider,
        BlotatoLinkedInProvider,
        BlotatoThreadsProvider,
        BlotatoTwitterProvider,
    )

    for cls in (
        BlotatoInstagramProvider,
        BlotatoFacebookProvider,
        BlotatoTwitterProvider,
        BlotatoLinkedInProvider,
        BlotatoThreadsProvider,
        BlotatoBlueskyProvider,
    ):
        assert hasattr(cls, "get_post_metrics")
        # The method must be defined on BlotatoProvider, not raise NotImplementedError.
        assert cls.get_post_metrics is BlotatoProvider.get_post_metrics


# ---------------------------------------------------------------------------
# get_account_metrics — should return empty AccountMetrics (no-op)
# ---------------------------------------------------------------------------

def test_get_account_metrics_returns_empty(monkeypatch):
    """Blotato has no account endpoint; should return zero AccountMetrics without HTTP calls."""
    p = _provider()
    call_count = {"n": 0}

    def fake_request(*a, **kw):
        call_count["n"] += 1
        return _resp({})

    monkeypatch.setattr(p, "_request", fake_request)

    import datetime as dt
    now = dt.datetime(2026, 6, 25, 12, 0, 0)
    result = p.get_account_metrics("tok", (now, now))

    assert isinstance(result, AccountMetrics)
    assert result.followers == 0
    assert result.impressions == 0
    assert call_count["n"] == 0  # no HTTP call made


# ---------------------------------------------------------------------------
# PLATFORM_METRICS catalog — blotato_* entries present and correct
# ---------------------------------------------------------------------------

def test_blotato_platforms_in_platform_metrics():
    """All six blotato_* platforms are registered in the analytics catalog."""
    from apps.analytics.metrics import PLATFORM_METRICS

    for platform in (
        "blotato_instagram",
        "blotato_facebook",
        "blotato_twitter",
        "blotato_linkedin",
        "blotato_threads",
        "blotato_bluesky",
    ):
        assert platform in PLATFORM_METRICS, f"{platform} missing from PLATFORM_METRICS"
        assert len(PLATFORM_METRICS[platform]) > 0, f"{platform} has empty metric list"


def test_blotato_instagram_metrics_include_standard_keys():
    from apps.analytics.metrics import PLATFORM_METRICS

    metrics = PLATFORM_METRICS["blotato_instagram"]
    for key in ("impressions", "reach", "likes", "comments", "shares", "saves", "views", "clicks"):
        assert key in metrics, f"blotato_instagram missing '{key}'"


def test_blotato_platforms_in_backfill_config():
    """All six blotato_* platforms get 90-day backfill window."""
    from apps.analytics.tasks import BACKFILL_DAYS_PER_PLATFORM

    for platform in (
        "blotato_instagram",
        "blotato_facebook",
        "blotato_twitter",
        "blotato_linkedin",
        "blotato_threads",
        "blotato_bluesky",
    ):
        assert BACKFILL_DAYS_PER_PLATFORM.get(platform, None) == 90, (
            f"{platform} should have 90-day backfill window"
        )


def test_blotato_platforms_in_credential_choices():
    """blotato_* must appear in PlatformCredential.Platform so enabled_platforms()
    fallback includes them on a fresh DB."""
    from apps.credentials.models import PlatformCredential

    choice_values = {v for v, _label in PlatformCredential.Platform.choices}
    for platform in (
        "blotato_instagram",
        "blotato_facebook",
        "blotato_twitter",
        "blotato_linkedin",
        "blotato_threads",
        "blotato_bluesky",
    ):
        assert platform in choice_values, (
            f"{platform} missing from PlatformCredential.Platform choices — "
            "enabled_platforms() fallback will exclude it"
        )
