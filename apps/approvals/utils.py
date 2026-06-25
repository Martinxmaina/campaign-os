"""Shared utilities for the approvals app."""
from __future__ import annotations

from django.conf import settings


def abs_url(path: str) -> str:
    """Return an absolute URL for *path* using the project's base-URL convention.

    Reads ``settings.STUDIO_BASE_URL`` (the canonical public origin used
    throughout this project — see ``apps/outreach/senders.py`` and
    ``apps/intelligence/views.py`` for the same pattern).  Falls back to
    ALLOWED_HOSTS or localhost so the helper never raises.
    """
    base = (getattr(settings, "STUDIO_BASE_URL", "") or "").strip().rstrip("/")
    if not base:
        hosts = [h for h in getattr(settings, "ALLOWED_HOSTS", []) if h and h not in ("*",)]
        base = f"https://{hosts[0]}" if hosts else "https://localhost"
    return f"{base}{path}"
