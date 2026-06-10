"""Normalization helpers for raw Google Sheets content-intake rows.

All functions are pure (no Django ORM calls) so they can be tested
without a database and imported anywhere in the pipeline.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# 1. Sensitivity
# ---------------------------------------------------------------------------

def normalize_sensitivity(raw: str) -> tuple[str, bool]:
    """Map a free-text sensitivity cell to a canonical value.

    Returns:
        (canonical_value, needs_review)

    Fail-closed: anything unrecognized → ("private_hold", True).
    """
    if not isinstance(raw, str):
        return "private_hold", True

    s = raw.strip()

    # public_safe variants
    if re.match(
        r"^(Public[\s\-]?safe|Public|public_safe|PUBLIC)$", s, re.IGNORECASE
    ):
        return "public_safe", False

    # partner_only
    if re.match(r"^partner[_\s]?only$", s, re.IGNORECASE):
        return "partner_only", False

    # confidential (prefix match)
    if re.match(r"^confidential", s, re.IGNORECASE):
        return "confidential", False

    # private_hold variants
    # Covers: private, Private, private_hold, Private Hold,
    #         "private, hold", "Private (don't post until …)"
    if re.match(
        r"^private",
        s,
        re.IGNORECASE,
    ):
        return "private_hold", False

    # Explicit "hold" phrase (e.g. "private, hold" already caught by prefix,
    # but catch standalone "hold" phrasing too)
    if re.match(r"^hold\b", s, re.IGNORECASE):
        return "private_hold", False

    # Anything else — fail closed
    return "private_hold", True


# ---------------------------------------------------------------------------
# 2. Channels
# ---------------------------------------------------------------------------

def _parse_single_channel(token: str) -> dict:
    """Parse a single channel token into a channel dict."""
    t = token.strip()

    # "Joseph personal" — personal LinkedIn post requiring Joseph approval
    if re.search(r"joseph\s+personal", t, re.IGNORECASE):
        return {
            "platform": "linkedin",
            "account": "joseph",
            "requires_joseph_approval": True,
        }

    # Gated brief / tease to signal.afcen.org
    if re.search(r"tease\s+to\s+signal|gated\s+brief", t, re.IGNORECASE):
        return {
            "platform": "linkedin",
            "companion": "gated_brief",
            "lead_capture": True,
        }

    # Cross-published / thought article
    if re.search(r"cross[\s\-]?publish|thought\s+article", t, re.IGNORECASE):
        return {"platform": "article", "multi_channel": True}

    # LinkedIn (WAIIS page)
    if re.search(r"linkedin.*waiis|waiis.*linkedin", t, re.IGNORECASE):
        return {"platform": "linkedin", "account": "waiis"}

    # Nexus Brief
    if re.search(r"nexus\s+brief", t, re.IGNORECASE):
        return {"platform": "nexus_brief"}

    # Generic LinkedIn
    if re.search(r"linkedin", t, re.IGNORECASE):
        return {"platform": "linkedin"}

    # Twitter / X
    if re.search(r"\btwitter\b|\bx\.com\b|\bx\s+post\b", t, re.IGNORECASE):
        return {"platform": "twitter"}

    # Newsletter / email
    if re.search(r"newsletter|email", t, re.IGNORECASE):
        return {"platform": "newsletter"}

    # Article / blog
    if re.search(r"\barticle\b|\bblog\b", t, re.IGNORECASE):
        return {"platform": "article"}

    # Fallback — preserve the raw value so the caller can route to review
    return {"platform": "unknown", "raw": t}


def parse_channels(raw: str) -> list[dict]:
    """Parse a free-text channel/target cell into a list of channel dicts.

    Compound entries separated by " + " are split into multiple items.
    """
    if not isinstance(raw, str) or not raw.strip():
        return []

    tokens = [t.strip() for t in raw.split(" + ") if t.strip()]
    return [_parse_single_channel(tok) for tok in tokens]


# ---------------------------------------------------------------------------
# 3. Status
# ---------------------------------------------------------------------------

def map_status(raw: str) -> tuple[str, bool]:
    """Map a free-text status cell to a canonical Status value.

    Returns:
        (canonical_status, needs_review)

    Anything unrecognized → ("review_queue", True).
    """
    if not isinstance(raw, str):
        return "review_queue", True

    s = raw.strip().lower()

    if s == "idea":
        return "idea", False

    # accept / greenlit / "post event piece"
    if re.search(r"post\s+event|accept|greenlit", s):
        return "accepted", False

    if re.search(r"\bdraft", s):
        return "drafting", False

    if re.search(r"\breview", s):
        return "in_review", False

    if re.search(r"\bapprov", s):
        return "approved", False

    if re.search(r"\bschedul", s):
        return "scheduled", False

    if re.search(r"\bpublish|\blive\b", s):
        return "published", False

    if re.search(r"\barchiv|\bdone\b", s):
        return "archived", False

    if re.search(r"\bhold|\bblock|\bwait", s):
        return "held", False

    return "review_queue", True


# ---------------------------------------------------------------------------
# 4. Unblock conditions
# ---------------------------------------------------------------------------

# Type constants (mirror UnblockCondition.ConditionType values)
_SOURCE_VERIFICATION = "source_verification"
_PARTNER_PERMISSION = "partner_permission"
_LEGAL_MILESTONE = "legal_milestone"
_FIGURE_CONFIRMATION = "figure_confirmation"


def extract_unblock_conditions(notes: str) -> list[dict]:
    """Extract structured unblock conditions from a free-text notes field.

    Patterns detected (case-insensitive):
    - verify source / check source         → source_verification
    - MoU / until sign / legal milestone   → legal_milestone  (overrides partner_permission)
    - partner / permission / KALRO /
      shareable / mou (without "sign")     → partner_permission
    - don't post until / not until /
      hold until                           → legal_milestone
    - confirm * range/figure/number/stat   → figure_confirmation

    Returns [] when no patterns match.
    Deduplicates by type (first occurrence wins).
    """
    if not isinstance(notes, str) or not notes.strip():
        return []

    n = notes.strip()
    found: dict[str, dict] = {}  # keyed by type for dedup

    def _add(ctype: str) -> None:
        if ctype not in found:
            found[ctype] = {"type": ctype, "description": n}

    # source_verification
    if re.search(r"\b(verify|check)\s+source", n, re.IGNORECASE):
        _add(_SOURCE_VERIFICATION)

    # legal_milestone (MoU + sign, hold-until, don't-post-until)
    mou_sign = re.search(r"\bMoU\b|\buntil\s+sign|\bdon['']?t\s+post\s+until|\bnot\s+until\b|\bhold\s+until\b", n, re.IGNORECASE)
    if mou_sign:
        _add(_LEGAL_MILESTONE)

    # partner_permission — keywords that suggest partner access, but NOT if
    # the legal_milestone keyword already captured it
    partner_pattern = re.search(
        r"\bKALRO\b|\bshareable\b|\bpartner\b|\bpermission\b|\bMoU\b",
        n,
        re.IGNORECASE,
    )
    if partner_pattern and _LEGAL_MILESTONE not in found:
        _add(_PARTNER_PERMISSION)

    # figure_confirmation
    if re.search(
        r"\bconfirm\b.{0,50}(range|figure|number|stat)",
        n,
        re.IGNORECASE,
        ):
        _add(_FIGURE_CONFIRMATION)

    return list(found.values())
