"""Gate-checked talking points for the pre-meeting cascade (TB.3).

The T-2 stage of ``meeting_prep`` drafts a short, opinionated set of talking
points from Joseph's L0 brief and then runs them through the SAME status-language
Pass-1 check the publish/composer path uses — so a premature "their board
confirmed" can never land verbatim on the brief before the deal actually clears.

- ``draft(thread) -> list[str]`` composes 3 bullets per track from the L0 brief's
  WHY-NOW + HOOK (via ``JosephIntelligence().brief``), degrading to a generic
  open/agenda/next-step skeleton when the dossier is empty (agent-service down).
- ``gate_talking_points(points) -> list[str]`` applies status-language Pass-1
  (the agent-service ``status_language`` rule: case-insensitive, word-boundary
  terms ``secured/committed/funded/approved/signed/confirmed``). A flagged term
  is neutralised in place (``confirmed`` → ``[unconfirmed]``) so the bullet is
  still usable but the premature status claim never survives. The gate is
  authoritative here exactly as on publish — no banned status word reaches the
  brief un-flagged.
"""
from __future__ import annotations

import re

from apps.joseph.intelligence import JosephIntelligence

# Status-language Pass-1 terms — kept in lockstep with the agent-service rule
# (app/gate/rules/status_language.yaml): case-insensitive, word-boundary. These
# assert a deal status that is not yet true; on a talking point they are
# rewritten to an explicitly-unconfirmed form rather than dropped.
# SEAM: when the gate moves in-process / agent-service exposes a sync local
# check, swap this constant for that single source of truth.
STATUS_LANGUAGE_TERMS = ("secured", "committed", "funded", "approved", "signed", "confirmed")


def draft(thread) -> list[str]:
    """Build 3 gate-able talking points for ``thread`` from its L0 brief.

    Pulls WHO / WHY-NOW / HOOK from ``JosephIntelligence().brief(thread)`` (the
    same L0 the surface renders) into an open → value → ask skeleton. Falls back
    to generic-but-useful bullets when the dossier is empty so the cascade always
    has something to gate and notify on, never an empty brief.
    """
    brief = JosephIntelligence().brief(thread) or {}
    who = (brief.get("who") or "").strip()
    why_now = (brief.get("why_now") or "").strip()
    hook = (brief.get("hook") or "").strip()

    opener = (
        f"Why now: {why_now}" if why_now
        else f"Open warm with {who}" if who
        else "Open warm; confirm shared context for this conversation"
    )
    value = (
        f"Lead with the hook — {hook}" if hook
        else "Lead with WAIIS's strongest, track-relevant hook"
    )
    ask = "Land one concrete next step (intro, follow-up doc, or a calendar hold)"

    return [opener, value, ask]


def gate_talking_points(points: list[str]) -> list[str]:
    """Run ``points`` through status-language Pass-1; neutralise flagged terms.

    Returns a list the same length as ``points``. Any status-language term is
    rewritten to an explicitly-unconfirmed marker (e.g. ``confirmed`` →
    ``[unconfirmed]``, ``committed`` → ``[uncommitted]``) so the bullet still
    reads but never asserts a status the deal hasn't reached. Clean points pass
    through byte-for-byte.
    """
    return [_scrub(p) for p in points]


def _scrub(point: str) -> str:
    text = point or ""
    for term in STATUS_LANGUAGE_TERMS:
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        text = pattern.sub(_neutral(term), text)
    return text


def _neutral(term: str) -> str:
    """The neutral replacement for a flagged status term.

    Deliberately omits the banned root word itself (so the scrubbed bullet can
    never be mistaken for the premature claim — ``[unconfirmed]`` would still
    contain "confirmed"): each maps to a plain "not-yet-true" marker.
    """
    return {
        "secured": "[in discussion]",
        "committed": "[exploring]",
        "funded": "[seeking support]",
        "approved": "[under review]",
        "signed": "[in discussion]",
        "confirmed": "[to be verified]",
    }[term.lower()]
