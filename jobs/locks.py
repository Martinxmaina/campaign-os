"""Redis distributed lock for non-reentrant beat tasks."""
from __future__ import annotations

import contextlib

import redis as redis_lib
from django.conf import settings


class LockNotAcquired(Exception):
    """Raised when a lock is already held by another worker."""


def _client():
    return redis_lib.Redis.from_url(settings.CELERY_BROKER_URL)


@contextlib.contextmanager
def redis_lock(name: str, ttl: int = 300):
    """Acquire ``lock:<name>`` via SET NX EX; raise LockNotAcquired if held."""
    client = _client()
    key = f"lock:{name}"
    if not client.set(key, "1", nx=True, ex=ttl):
        raise LockNotAcquired(name)
    try:
        yield
    finally:
        client.delete(key)
