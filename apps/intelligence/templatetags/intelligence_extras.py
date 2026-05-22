"""Template helpers for the Intelligence playground partials."""

from __future__ import annotations

from django import template


register = template.Library()


@register.filter
def humanize_slug(value):
    """Turn a snake_case slug into Title-cased display text.

    ``bold_claim`` → ``Bold claim``, ``pattern_interrupt`` →
    ``Pattern interrupt``. Falls back to ``str(value)`` for non-string
    inputs so callers don't need to null-check before piping.
    """
    if value is None:
        return ""
    text = str(value).replace("_", " ").replace("-", " ").strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:]


@register.filter
def score_pct(value):
    """Convert a sub-score on the 0–10 axis into an integer percent for
    progress-bar widths in templates. Clamps to [0, 100] so a 12/10
    score doesn't overflow the bar visually."""
    try:
        pct = int(round(float(value) * 10))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, pct))
