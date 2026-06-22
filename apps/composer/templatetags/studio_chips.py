"""Template helpers for the Content Studio board chips (Task 4).

The board's filter chips reuse the canonical segmentation taxonomy from
``apps.composer.segments`` (track = CRM canon; pillar = owner_routing sectors)
so the UI never invents its own choice set. ``studio_qs`` builds a ``?param=``
querystring that preserves the *other* active filters while overriding one — so
every chip is a plain GET navigation (CSP-safe, no JS). ``dict_get`` reads the
Task 3 per-segment counts by key for display next to a chip.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django import template

from apps.composer import segments

register = template.Library()

# Working states surfaced as chips on the board (subset of the derived
# post-level statuses — the states a content lead acts on).
STATE_CHIPS = [
    ("draft", "Draft"),
    ("pending_review", "Pending review"),
    ("approved", "Approved"),
    ("scheduled", "Scheduled"),
    ("published", "Published"),
]


@register.simple_tag
def studio_qs(active, **overrides):
    """Build a querystring from the ``active`` filter dict + ``overrides``.

    ``active`` is the view's echoed filter map (track/pillar/campaign/state/q).
    Each override replaces (or clears, when "") that single param while every
    other active filter is preserved — so a chip narrows on one axis without
    losing the rest. Empty values are dropped so an "All" chip links back to a
    clean axis.
    """
    params = {
        "track": (active or {}).get("track", ""),
        "pillar": (active or {}).get("pillar", ""),
        "campaign": (active or {}).get("campaign", ""),
        "state": (active or {}).get("state", ""),
        "q": (active or {}).get("q", ""),
    }
    params.update(overrides)
    return urlencode({k: v for k, v in params.items() if v})


@register.filter
def dict_get(mapping, key):
    """Read ``mapping[key]`` (counts dict) with a safe default for templates."""
    if not mapping:
        return None
    return mapping.get(key)


@register.simple_tag
def track_chips():
    """Canonical track choices for the board chips."""
    return segments.TRACK_CHOICES


@register.simple_tag
def pillar_chips():
    """Canonical pillar choices for the board chips."""
    return segments.PILLAR_CHOICES


@register.simple_tag
def state_chips():
    """Working-state choices for the board chips."""
    return STATE_CHIPS
