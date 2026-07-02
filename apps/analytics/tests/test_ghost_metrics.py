"""Analytics-layer wiring for Ghost subscriber metrics."""
from __future__ import annotations

from apps.analytics.metrics import METRICS, PLATFORM_METRICS, PLATFORM_PRIMARY
from apps.analytics.tasks import BACKFILL_DAYS_PER_PLATFORM, _account_metrics_to_dict
from providers.types import AccountMetrics


def test_ghost_in_platform_metrics_with_subscribers():
    assert "ghost" in PLATFORM_METRICS
    # A followers-style growth metric mapped to members, labelled "Subscribers".
    assert "subscribers" in PLATFORM_METRICS["ghost"]
    assert METRICS["subscribers"]["label"] == "Subscribers"


def test_ghost_primary_metric_is_subscribers():
    assert PLATFORM_PRIMARY.get("ghost") == "subscribers"


def test_ghost_has_backfill_entry():
    # Account metrics are a lifetime member snapshot, but per-POST metrics DO
    # exist (link clicks always; newsletter reach + opens for emailed posts), so
    # post sync is enabled with a real window.
    assert BACKFILL_DAYS_PER_PLATFORM.get("ghost") == 30


def test_account_metrics_to_dict_persists_ghost_subscribers():
    metrics = AccountMetrics(followers=4231, extra={"subscribers": 4231})
    out = _account_metrics_to_dict(metrics, "ghost")
    assert out.get("subscribers") == 4231.0
