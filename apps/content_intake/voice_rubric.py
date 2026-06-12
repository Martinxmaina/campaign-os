# apps/content_intake/voice_rubric.py
"""Score text against a voice profile (TB.1 validation rubric)."""
from __future__ import annotations
import re


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def score_voice(text: str, channel: str, profile: dict) -> dict:
    failures: list[str] = []
    low = (text or "").lower()

    for phrase in profile.get("banned_phrases", []):
        if phrase.lower() in low:
            failures.append(f"banned phrase present: {phrase!r}")

    stripped = (text or "").lstrip()
    if stripped[:2].lower() == "i " or stripped[:2] == "I'":
        failures.append("opener starts with 'I'")
    if channel == "linkedin" and stripped[:80].strip().endswith("?"):
        failures.append("LinkedIn opener is a question")

    rng = (profile.get("length_by_channel") or {}).get(channel)
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        wc = _word_count(text)
        if wc < rng[0] or wc > rng[1]:
            failures.append(f"length {wc} out of range {rng[0]}-{rng[1]} for {channel}")

    return {"passed": not failures, "failures": failures}
