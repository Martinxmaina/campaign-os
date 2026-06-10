import pytest

from jobs.locks import redis_lock, LockNotAcquired


class FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, val, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = (val.encode() if isinstance(val, str) else val)
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)

    def register_script(self, script):
        """Minimal Lua-script stub: compare-and-delete by token."""
        def run(keys, args):
            key = keys[0]
            token = args[0].encode() if isinstance(args[0], str) else args[0]
            if self.store.get(key) == token:
                self.store.pop(key, None)
                return 1
            return 0
        return run


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


def test_slow_holder_does_not_delete_new_holders_lock(monkeypatch):
    """Token-checked release: slow cycle's finally must not evict a newer holder.

    Sequence:
    1. Slow cycle acquires the lock (token A), stores the context manager.
    2. Slow cycle's TTL expires; a new cycle acquires the same key (token B).
    3. Slow cycle's finally block runs — it must NOT delete the new holder's lock.
    """
    fake = FakeRedis()
    monkeypatch.setattr("jobs.locks._client", lambda: fake)

    import contextlib

    # Acquire as "slow" holder — keep the CM object without exiting yet.
    slow_cm = redis_lock("job:z", ttl=10)
    slow_cm.__enter__()

    # Simulate TTL expiry: remove key from store manually.
    key = "lock:job:z"
    fake.store.pop(key, None)

    # A new holder acquires the lock (different token).
    new_cm = redis_lock("job:z", ttl=10)
    new_cm.__enter__()
    new_token = fake.store.get(key)

    # Slow holder exits — its token no longer matches; must NOT delete new holder's key.
    slow_cm.__exit__(None, None, None)

    # New holder's lock must still be present.
    assert fake.store.get(key) == new_token, (
        "slow holder's release erroneously deleted the new holder's lock"
    )

    # Clean up new holder properly.
    new_cm.__exit__(None, None, None)
    assert key not in fake.store
