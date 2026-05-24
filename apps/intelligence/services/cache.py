"""Per-request memoization for /v1/me and /v1/usage.

These are read on every Intelligence-related page render (header
credit counter, etc.); without memoization a single page can fire
multiple identical Intelligence calls. The cache lives on the
``request`` object so it's automatically discarded at request end,
no Redis dependency, no stale-cache problems.
"""

from __future__ import annotations

from typing import Callable, TypeVar


_T = TypeVar("_T")


def per_request_cache(request, key: tuple, producer: Callable[[], _T]) -> _T:
    """Return ``producer()`` once per request for the given key.

    ``key`` is a tuple of stable identifiers (e.g. ``(org_id, "me")``).
    """
    bucket = getattr(request, "_intelligence_cache", None)
    if bucket is None:
        bucket = {}
        request._intelligence_cache = bucket
    if key in bucket:
        return bucket[key]
    value = producer()
    bucket[key] = value
    return value
