"""Analytics-layer wiring for LinkedIn Company follower metrics.

The provider test (tests/providers/test_linkedin_company_analytics.py) checks
``get_account_metrics`` in isolation, but the followers value is silently
dropped unless ``linkedin_company`` lists ``followers`` in its catalog — these
tests exercise the persistence gate (``_account_metrics_to_dict``) end-to-end.
"""
from __future__ import annotations

from apps.analytics.metrics import METRICS, PLATFORM_METRICS
from apps.analytics.tasks import _account_metrics_to_dict
from providers.types import AccountMetrics


def test_linkedin_company_in_platform_metrics_with_followers():
    assert "linkedin_company" in PLATFORM_METRICS
    # firstDegreeSize -> followers (lifetime total), labelled "Followers".
    assert "followers" in PLATFORM_METRICS["linkedin_company"]
    assert METRICS["followers"]["label"] == "Followers"


def test_account_metrics_to_dict_persists_linkedin_company_followers():
    """The followers count the provider returns must survive the persistence
    gate — mirrors the tiktok lifetime-total mapping."""
    metrics = AccountMetrics(followers=8421)
    out = _account_metrics_to_dict(metrics, "linkedin_company")
    assert out.get("followers") == 8421.0


def test_account_metrics_to_dict_writes_zero_followers_baseline():
    """A brand-new page with 0 followers still gets a baseline row so the
    chart can render a continuous line (``is not None`` semantics)."""
    out = _account_metrics_to_dict(AccountMetrics(followers=0), "linkedin_company")
    assert out.get("followers") == 0.0
