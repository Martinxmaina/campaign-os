"""Redis distributed lock for non-reentrant beat tasks."""
from __future__ import annotations

import contextlib
import uuid

import redis as redis_lib
from django.conf import settings

# Lua compare-and-delete: only removes the key when the stored value matches
# the caller's token, preventing a slow holder from evicting a newer holder's
# lock after a TTL expiry.
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class LockNotAcquired(Exception):
    """Raised when a lock is already held by another worker."""


def _client():
    return redis_lib.Redis.from_url(settings.CELERY_BROKER_URL)


@contextlib.contextmanager
def redis_lock(name: str, ttl: int = 300):
    """Acquire ``lock:<name>`` via SET NX EX; raise LockNotAcquired if held.

    The lock value is a random UUID token so that the release step uses a
    compare-and-delete (Lua script) rather than an unconditional DEL.  This
    prevents a slow holder whose TTL has expired from evicting the lock that a
    new holder has already acquired.
    """
    client = _client()
    key = f"lock:{name}"
    token = str(uuid.uuid4())
    if not client.set(key, token, nx=True, ex=ttl):
        raise LockNotAcquired(name)
    release = client.register_script(_RELEASE_SCRIPT)
    try:
        yield
    finally:
        release(keys=[key], args=[token])
