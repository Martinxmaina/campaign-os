"""Extraction seam for the meeting-capture loop (TB.4, Task 5).

# SEAM: real agent-service ATLAS extraction pass wires in here later — this is a
# pure function with a stable shape (``extract(transcript, thread) -> dict``) so
# the whole capture→extract→confirm loop is testable and shippable today;
# swapping in the real model is a one-function change with the tests already
# written.

The deterministic heuristic below sentence-splits the transcript and keyword-
matches each sentence into the structured outcome the confirm screen (Task 6)
routes on. The shape is stable and exercises the full routing-set; it is NOT an
attempt at real NLU (that is the ATLAS swap):

    {
        "commitments": [{"kind", "description", "verbatim_quote", "confidence"}],
        "next_steps":  [{"description", "verbatim_quote", "confidence"}],
        "intelligence_signals": [{"description", "verbatim_quote",
                                  "wiki_update_candidate", "confidence"}],
        "content_ideas": [{"description", "verbatim_quote", "confidence"}],
        "warmth_delta": "warmer|same|cooler|''",
        "relationship_notes": str,
    }
"""
from __future__ import annotations

import re

# Keyword cues that map a sentence to a routing kind. Order matters: commitments
# are checked before generic next-steps so "I will send" doesn't shadow a fund
# commitment. Each entry is (substrings, classifier).
_COMMITMENT_FINANCIAL = ("fund", "funding", "grant", "invest", "million", "budget")
_COMMITMENT_INTRO = ("introduce", "introduction", "connect you", "warm intro")
_COMMITMENT_FOLLOW_UP = ("committed", "commit", "agreed", "promised", "will follow")
_NEXT_STEP = ("next step", "i will", "we will", "send", "schedule", "follow up", "by ")
_INTELLIGENCE = ("mentioned", "signal", "policy", "heard", "noted", "concern", "rumour")
_CONTENT_IDEA = ("content", "story", "post", "article", "publish", "write about")
_WARMER = ("excited", "enthusiastic", "keen", "warmer", "promising", "great meeting")
_COOLER = ("hesitant", "concerned", "cooler", "pushed back", "not sure", "reluctant")


def extract(transcript: str, thread) -> dict:
    """Heuristically map a transcript into the stable structured outcome dict.

    # SEAM: real agent-service ATLAS pass later. ``thread`` is accepted for the
    real signature (the ATLAS call grounds on the thread/dossier) but the
    placeholder heuristic ignores it. Deterministic for a given transcript.
    """
    sentences = _split(transcript)

    commitments: list[dict] = []
    next_steps: list[dict] = []
    intelligence_signals: list[dict] = []
    content_ideas: list[dict] = []
    warmer = cooler = False

    for sent in sentences:
        low = sent.lower()
        matched = False

        if _any(low, _COMMITMENT_FINANCIAL):
            commitments.append(_commitment(sent, "commitment_financial"))
            matched = True
        elif _any(low, _COMMITMENT_INTRO):
            commitments.append(_commitment(sent, "commitment_intro"))
            matched = True
        elif _any(low, _COMMITMENT_FOLLOW_UP):
            commitments.append(_commitment(sent, "commitment_follow_up"))
            matched = True

        if _any(low, _CONTENT_IDEA):
            content_ideas.append(_signal(sent))
            matched = True

        if not matched and _any(low, _NEXT_STEP):
            next_steps.append(_signal(sent))
            matched = True

        if _any(low, _INTELLIGENCE):
            sig = _signal(sent)
            sig["wiki_update_candidate"] = True
            intelligence_signals.append(sig)

        if _any(low, _WARMER):
            warmer = True
        if _any(low, _COOLER):
            cooler = True

    warmth_delta = ""
    if warmer and not cooler:
        warmth_delta = "warmer"
    elif cooler and not warmer:
        warmth_delta = "cooler"

    return {
        "commitments": commitments,
        "next_steps": next_steps,
        "intelligence_signals": intelligence_signals,
        "content_ideas": content_ideas,
        "warmth_delta": warmth_delta,
        "relationship_notes": (transcript or "").strip(),
    }


def _split(transcript: str) -> list[str]:
    """Split a transcript into trimmed, non-empty sentences."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", transcript or "")
    return [p.strip() for p in parts if p.strip()]


def _any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(n in haystack for n in needles)


def _commitment(sentence: str, kind: str) -> dict:
    return {
        "kind": kind,
        "description": sentence,
        "verbatim_quote": sentence,
        "confidence": 0.7,
    }


def _signal(sentence: str) -> dict:
    return {
        "description": sentence,
        "verbatim_quote": sentence,
        "confidence": 0.6,
    }
