import pytest
from django.core.cache import cache
from django.utils import timezone


@pytest.mark.django_db
def test_heartbeat_writes_cache_key():
    from jobs.tasks import beat_heartbeat
    cache.delete("beat:heartbeat")
    beat_heartbeat()
    assert cache.get("beat:heartbeat") is not None


@pytest.mark.django_db
def test_health_returns_503_when_beat_unknown(client):
    """No heartbeat in cache -> beat=unknown -> HTTP 503 (deploy gate must fail)."""
    cache.delete("beat:heartbeat")
    resp = client.get("/health/")
    assert resp.status_code == 503
    body = resp.json()
    assert body["beat"] == "unknown"


@pytest.mark.django_db
def test_health_returns_503_when_beat_stale(client):
    """Old heartbeat -> beat=stale -> HTTP 503."""
    from datetime import timedelta
    stale_ts = (timezone.now() - timedelta(seconds=300)).isoformat()
    cache.set("beat:heartbeat", stale_ts, timeout=600)
    resp = client.get("/health/")
    assert resp.status_code == 503
    body = resp.json()
    assert body["beat"] == "stale"


@pytest.mark.django_db
def test_health_returns_200_when_beat_fresh(client):
    """Recent heartbeat -> beat=fresh -> HTTP 200."""
    cache.set("beat:heartbeat", timezone.now().isoformat(), timeout=300)
    resp = client.get("/health/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["beat"] == "fresh"
    assert body["status"] == "ok"
