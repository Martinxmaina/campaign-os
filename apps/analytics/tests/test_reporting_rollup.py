"""Unit tests for the workspace analytics rollup builders."""
from __future__ import annotations

import pytest
from django.utils import timezone


@pytest.fixture
def setup(db):
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="R Org")
    ws = Workspace.objects.create(name="R WS", organization=org)
    ig = SocialAccount.objects.create(
        workspace=ws, platform="instagram", account_platform_id="ig-r",
        account_name="IG", connection_status="connected", follower_count=100,
    )
    return ws, ig


@pytest.mark.django_db
def test_rollup_unavailable_when_no_accounts():
    from apps.analytics.api_builders import account_metric_map, build_workspace_analytics_rollup

    rollup = build_workspace_analytics_rollup(account_metric_map([], 30), 30)
    assert rollup.available is False
    assert rollup.accounts == 0
    assert rollup.totals == {}
    assert rollup.by_platform == []


def test_rollup_sums_across_accounts():
    """Pure summation: totals add up across accounts; per-platform groups."""
    from apps.analytics.api_builders import build_workspace_analytics_rollup

    account_map = {
        "a": {"platform": "linkedin", "available": True, "metrics": {"impressions": 100.0, "likes": 5.0}},
        "b": {"platform": "linkedin", "available": True, "metrics": {"impressions": 50.0}},
        "c": {"platform": "x", "available": True, "metrics": {"impressions": 10.0}},
        "d": {"platform": "instagram", "available": False, "metrics": {"impressions": 999.0}},  # excluded
    }
    rollup = build_workspace_analytics_rollup(account_map, 30)
    assert rollup.available is True
    assert rollup.accounts == 3  # the unavailable account is excluded
    assert rollup.totals["impressions"] == 160.0
    assert rollup.totals["likes"] == 5.0
    by_platform = {p.platform: p.metrics for p in rollup.by_platform}
    assert by_platform["linkedin"]["impressions"] == 150.0
    assert by_platform["x"]["impressions"] == 10.0
    assert "instagram" not in by_platform


@pytest.mark.django_db
def test_account_metric_map_marks_availability(setup):
    """account_metric_map runs build_account_analytics per account and records
    its availability + platform without coupling to specific metric keys."""
    from apps.analytics.api_builders import account_metric_map

    ws, ig = setup
    amap = account_metric_map([ig], 30)
    assert ig.id in amap
    entry = amap[ig.id]
    assert entry["platform"] == "instagram"
    assert entry["available"] is True
    assert isinstance(entry["metrics"], dict)
