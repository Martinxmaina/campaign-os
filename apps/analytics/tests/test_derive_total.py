"""Regression: cumulative-total metrics (followers/subscribers) must be the LATEST
snapshot, not the SUM over the window. (Ghost showed 2622 = 2 × 1311 from summing.)
"""
from apps.analytics.derive import derive, kind_of


def test_total_kind_takes_latest_not_sum():
    # two daily snapshots of a lifetime total — must read 1311, not 2622
    m = derive([1311.0, 1311.0], days=1, kind="total")
    assert m.value == 1311.0
    # net-growth delta is 0 when the total is unchanged
    assert m.delta == 0.0


def test_total_kind_growth_delta():
    m = derive([1300.0, 1320.0], days=1, kind="total")
    assert m.value == 1320.0            # current total
    assert m.delta > 0                  # grew vs the previous window


def test_count_kind_still_sums():
    # additive per-day metrics (impressions/likes) still sum over the window
    m = derive([10.0, 5.0], days=1, kind="count")
    assert m.value == 5.0               # days=1 → window is the last day only
    m2 = derive([10.0, 5.0], days=2, kind="count")
    assert m2.value == 15.0             # two-day window sums


def test_followers_and_subscribers_are_total_kind():
    assert kind_of("followers") == "total"
    assert kind_of("subscribers") == "total"
