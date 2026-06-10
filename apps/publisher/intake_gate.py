"""Pre-dispatch intake sensitivity and condition gate check."""
from __future__ import annotations
import logging

from apps.content_intake.models import ContentIntake, UnblockCondition

logger = logging.getLogger(__name__)

# Single source of truth: use the enum constants so any rename/value change
# on the TextChoices propagates here automatically without silent failures.
_BLOCKED_SENSITIVITIES = frozenset([
    ContentIntake.Sensitivity.PRIVATE_HOLD,
    ContentIntake.Sensitivity.CONFIDENTIAL,
])


def check_intake_gate(intake) -> tuple[bool, str]:
    """Return (is_blocked, reason). intake may be None → (False, "")."""
    if intake is None:
        return False, ""
    if intake.sensitivity in _BLOCKED_SENSITIVITIES:
        open_conds = list(
            intake.unblock_conditions
            .filter(status=UnblockCondition.ConditionStatus.OPEN)
            .values_list("description", flat=True)
        )
        return True, f"Content is {intake.sensitivity} — cannot publish. Open conditions: {open_conds}"
    if intake.proof_status == ContentIntake.ProofStatus.NEEDS_VERIFICATION:
        return True, f"Proof point requires verification before publishing. Intake: {intake.external_id}"
    open_conditions = list(
        intake.unblock_conditions
        .filter(status=UnblockCondition.ConditionStatus.OPEN)
        .values("condition_type", "description")
    )
    if open_conditions:
        descriptions = "; ".join(c["description"] for c in open_conditions)
        return True, f"Unblock conditions still open: {descriptions}"
    return False, ""
