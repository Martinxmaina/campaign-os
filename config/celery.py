"""Celery application for Campaign OS.

Broker + result backend share the Redis instance pointed at by REDIS_URL.
We push the broker to logical DB index 1 so it never collides with the
Django cache (which uses the URL as given, typically /0).
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

from celery import Celery


def build_broker_url(redis_url: str) -> str:
    """Return REDIS_URL with the path forced to logical DB /1 for the broker."""
    if not redis_url:
        # Local/dev fallback; tests run eager so this is never dialed.
        return "redis://localhost:6379/1"
    parts = urlsplit(redis_url)
    return urlunsplit((parts.scheme, parts.netloc, "/1", parts.query, parts.fragment))


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("campaign_os")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
