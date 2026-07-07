"""HERALD curation for TWG meetings.

Runs the ``docs/herald-prompts/`` instruction (HERALD.md + curation + the
house / pillar / platform knowledge layers) through DeepSeek against a
public-safe meeting payload, and returns HERALD's JSON content plan
``{decision, reason, posts[], excluded[]}``.

Fail-safe by design: any problem — engine down, unparseable output, malformed
shape — resolves to ``decision="hold"`` (route to a human), never a silent or
accidental publish.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from apps.common import deepseek_client

logger = logging.getLogger(__name__)

_PROMPTS = Path(settings.BASE_DIR) / "docs" / "herald-prompts"

# twg_pillar substring → pillar file slug (digital + ai collapse into one).
_PILLAR_MATCH = {
    "agribusiness": "agribusiness",
    "food": "agribusiness",
    "energy": "energy",
    "power": "energy",
    "mineral": "minerals",
    "mining": "minerals",
    "digital": "digital-innovation",
    "innovation": "digital-innovation",
    "ai": "digital-innovation",
}


@lru_cache(maxsize=32)
def _read(rel: str) -> str:
    try:
        return (_PROMPTS / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


def _pillar_slug(twg_pillar: str) -> str:
    t = (twg_pillar or "").lower()
    for key, slug in _PILLAR_MATCH.items():
        if key in t:
            return slug
    return ""


def herald_platform(account_platform: str) -> str | None:
    """Map a SocialAccount.platform to HERALD's platform key (or None to skip)."""
    p = (account_platform or "").lower()
    if "linkedin" in p:
        return "linkedin"
    if "twitter" in p or p == "x":
        return "x"
    if "instagram" in p:
        return "instagram"
    if p == "ghost":
        return "ghost"
    return None


def _build_prompt(payload: dict, pillar_slug: str, platforms: list[str]) -> tuple[str, str]:
    parts = [_read("HERALD.md"), _read("curation.md"), _read("workspaces/waiis.md")]
    if pillar_slug:
        parts.append(_read(f"pillars/{pillar_slug}.md"))
    for p in platforms:
        parts.append(_read(f"platforms/{p}.md"))
    system = "\n\n---\n\n".join(x for x in parts if x)
    user = (
        "TARGET PLATFORMS: " + ", ".join(platforms) + "\n\n"
        "MEETING (public-safe payload):\n" + json.dumps(payload, indent=2) + "\n\n"
        "Curate and return the JSON output contract now. Output JSON only."
    )
    return system, user


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _hold(reason: str) -> dict:
    return {"decision": "hold", "reason": reason, "posts": [], "excluded": []}


def curate(payload: dict, platforms: list[str]) -> dict:
    """Return HERALD's plan ``{decision, reason, posts[], excluded[]}``.

    ``decision`` ∈ {publish, hold, none}. Fail-safe: any failure → ``hold``.
    """
    if not platforms:
        return _hold("no target platforms connected")
    if not deepseek_client.deepseek_available():
        return _hold("drafting engine unavailable")

    system, user = _build_prompt(payload, _pillar_slug(payload.get("twg_pillar", "")), platforms)
    raw = deepseek_client.chat(system, user, temperature=0.5, max_tokens=4000)
    data = _extract_json(raw)
    if not isinstance(data, dict) or data.get("decision") not in ("publish", "hold", "none"):
        logger.warning("HERALD: unparseable/invalid response (%d chars)", len(raw or ""))
        return _hold("could not parse a valid HERALD response")
    if not isinstance(data.get("posts"), list):
        return _hold("HERALD returned malformed posts")
    data.setdefault("reason", "")
    data.setdefault("excluded", [])
    return data
