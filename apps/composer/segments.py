# apps/composer/segments.py
"""Content Studio segmentation taxonomy: track / pillar choice sets + normalizers.

A draft Post is segmented by House (= its workspace) · Pillar · Track · Campaign.
This module owns the canonical *Track* and *Pillar* choice sets plus the
normalizers that carry an intake row's free-text pillar_theme onto the Post.

Reuse, not reinvention:
- Track values mirror the CRM canon ``core / ai10bn / waiis / programs``.
- Pillar values are exactly the sectors keyed in
  ``apps.content_intake.owner_routing.OWNER_BY_PILLAR``
  (energy / agribusiness / ai / digital / minerals).
- ``normalize_pillar`` runs the intake ``sector_map.map_pillar_to_sector`` first
  (so "AI for Agriculture" -> ai, "Solar power" -> energy), then falls back to a
  direct lowercase match for the pillars the sector_map doesn't classify
  (digital, minerals). Anything unrecognised returns "" — blank is always a
  valid (editable-later) Post value, never an invalid choice.
"""
from __future__ import annotations

from apps.content_intake.owner_routing import OWNER_BY_PILLAR
from apps.content_intake.sector_map import map_pillar_to_sector

# Track — canonical four (apps/crm/models.py taxonomy). Order is meaningful for
# select rendering; "core" first.
TRACK_CHOICES = [
    ("core", "Core"),
    ("ai10bn", "AI $10bn"),
    ("waiis", "WAIIS"),
    ("programs", "Programs"),
]

# Pillar — exactly the sectors owner_routing routes on.
_PILLAR_LABELS = {
    "energy": "Energy",
    "agribusiness": "Agribusiness",
    "ai": "AI",
    "digital": "Digital",
    "minerals": "Minerals",
}
PILLAR_CHOICES = [(value, _PILLAR_LABELS[value]) for value in OWNER_BY_PILLAR]

_VALID_TRACKS = {value for value, _ in TRACK_CHOICES}
_VALID_PILLARS = {value for value, _ in PILLAR_CHOICES}


def normalize_pillar(pillar_theme: str) -> str:
    """Map a free-text pillar/theme to a canonical Post pillar, or "".

    1. Run the intake sector_map (ai/energy/agribusiness wins on explicit signal).
    2. If the sector_map says "general", try a direct lowercase match so the
       pillars it doesn't classify (digital, minerals) still resolve.
    3. Unrecognised -> "" (blank, editable later — never an invalid choice).
    """
    text = (pillar_theme or "").strip()
    if not text:
        return ""
    sector = map_pillar_to_sector(text)
    if sector in _VALID_PILLARS:
        return sector
    direct = text.lower()
    if direct in _VALID_PILLARS:
        return direct
    # Loose substring fallback for the un-mapped pillars (e.g. "Minerals & mining").
    for value in _VALID_PILLARS:
        if value in direct:
            return value
    return ""


def normalize_track(value: str) -> str:
    """Return ``value`` if it is a canonical track, else "" (blank)."""
    v = (value or "").strip().lower()
    return v if v in _VALID_TRACKS else ""


def infer_track(*texts: str) -> str:
    """Best-effort track inference from free text; "" when no signal.

    Conservative on purpose — only fires on unambiguous signals so a wrong
    track is never silently set. The editor can always pick one later.
    """
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return ""
    if "ai10bn" in blob or "ai $10bn" in blob or "$10bn" in blob or "10bn" in blob:
        return "ai10bn"
    if "waiis" in blob:
        return "waiis"
    if "programme" in blob or "program" in blob:
        return "programs"
    return ""
