# apps/content_intake/sector_map.py
"""Map a free-text pillar/theme string to a canonical agent-service sector.

The agent-service accepts only: energy | agribusiness | ai | general.
"""
import re

_RULES = [
    (re.compile(r"energy|power|electri|renewable|solar|grid", re.I), "energy"),
    (re.compile(r"agri|farm|food|crop|kalro|livestock", re.I), "agribusiness"),
    (re.compile(r"\bai\b|artificial intelligence|10bn|machine learning", re.I), "ai"),
]


def map_pillar_to_sector(pillar_theme: str) -> str:
    text = (pillar_theme or "").strip()
    for pattern, sector in _RULES:
        if pattern.search(text):
            return sector
    return "general"
