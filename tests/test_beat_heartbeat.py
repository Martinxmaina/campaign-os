import pytest
from django.core.cache import cache


@pytest.mark.django_db
def test_heartbeat_writes_cache_key():
    from jobs.tasks import beat_heartbeat
    cache.delete("beat:heartbeat")
    beat_heartbeat()
    assert cache.get("beat:heartbeat") is not None


@pytest.mark.django_db
def test_health_reports_beat_staleness(client):
    cache.delete("beat:heartbeat")
    resp = client.get("/health/")
    assert resp.status_code in (200, 503)
    assert "beat" in resp.json()
