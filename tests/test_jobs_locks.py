import pytest

from jobs.locks import redis_lock, LockNotAcquired


class FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, val, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = val
        return True

    def delete(self, key):
        self.store.pop(key, None)


def test_lock_acquires_and_releases(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("jobs.locks._client", lambda: fake)
    with redis_lock("job:x", ttl=10):
        assert "lock:job:x" in fake.store
    assert "lock:job:x" not in fake.store


def test_second_lock_within_ttl_is_refused(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("jobs.locks._client", lambda: fake)
    with redis_lock("job:y", ttl=10):
        with pytest.raises(LockNotAcquired):
            with redis_lock("job:y", ttl=10):
                pass
