# apps/content_intake/sector_map.py
"""Map a free-text pillar/theme string to a canonical agent-service sector.

The agent-service accepts only: energy | agribusiness | ai | general.

Precedence (documented + enforced, highest first):
    1. ai           — an explicit AI signal is the most specific intent and
                      wins over cross-cutting domain words. So
                      "AI for Agriculture" -> ai and "Solar AI platform" -> ai.
    2. energy
    3. agribusiness
    4. general       — no rule matched.

Rationale: domain words like "agri" or "solar" are common context for an AI
initiative, but when a pillar explicitly names AI that is the canonical bucket
the agent-service should route to. Within energy vs agribusiness there is no
known overlap, so their relative order does not affect classification.

Token safety: high-risk broad tokens are anchored with word boundaries so they
do not fire on unrelated words, e.g. ``\bpower\b`` does NOT match
"empowerment"/"manpower", and ``\bfood\b`` does NOT match "seafood". Narrower
stems (``agri``, ``electri``, ``renewable``) stay as substrings on purpose so
they catch "agriculture"/"agribusiness" and "electricity".
"""
import re

# Ordered by precedence (first match wins). ``ai`` is deliberately first so an
# explicit AI signal beats cross-cutting domain words. See module docstring.
_RULES = [
    (
        re.compile(r"\bai\b|artificial intelligence|10bn|machine learning", re.I),
        "ai",
    ),
    (
        re.compile(
            r"\benergy\b|\bpower\b|electri|renewable|solar|\bgrid\b", re.I
        ),
        "energy",
    ),
    (
        re.compile(r"agri|farm|\bfood\b|crop|kalro|livestock", re.I),
        "agribusiness",
    ),
]


def map_pillar_to_sector(pillar_theme: str) -> str:
    text = (pillar_theme or "").strip()
    for pattern, sector in _RULES:
        if pattern.search(text):
            return sector
    return "general"
