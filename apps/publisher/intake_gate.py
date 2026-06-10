"""Pre-dispatch intake sensitivity and condition gate check."""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

_BLOCKED_SENSITIVITIES = frozenset(["private_hold", "confidential"])

def check_intake_gate(intake) -> tuple[bool, str]:
    """Return (is_blocked, reason). intake may be None → (False, "")."""
    if intake is None:
        return False, ""
    if intake.sensitivity in _BLOCKED_SENSITIVITIES:
        open_conds = list(intake.unblock_conditions.filter(status="open").values_list("description", flat=True))
        return True, f"Content is {intake.sensitivity} — cannot publish. Open conditions: {open_conds}"
    if intake.proof_status == "needs_verification":
        return True, f"Proof point requires verification before publishing. Intake: {intake.external_id}"
    open_conditions = list(intake.unblock_conditions.filter(status="open").values("condition_type", "description"))
    if open_conditions:
        descriptions = "; ".join(c["description"] for c in open_conditions)
        return True, f"Unblock conditions still open: {descriptions}"
    return False, ""
