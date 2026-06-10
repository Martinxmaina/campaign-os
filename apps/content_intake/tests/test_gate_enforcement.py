"""Tests for check_intake_gate() — intake sensitivity and unblock-condition blocking."""
import pytest

from apps.content_intake.models import ContentIntake, UnblockCondition
from apps.publisher.intake_gate import check_intake_gate


@pytest.mark.django_db
def test_private_hold_intake_is_blocked(workspace):
    """private_hold sensitivity → (True, reason containing 'private_hold')."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="GATE-001",
        pillar_theme="Energy",
        sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
        status=ContentIntake.Status.ACCEPTED,
    )
    blocked, reason = check_intake_gate(intake)
    assert blocked is True
    assert "private_hold" in reason


@pytest.mark.django_db
def test_open_legal_milestone_condition_is_blocked(workspace):
    """Open legal_milestone unblock condition → (True, reason containing 'condition' or 'unblock')."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="GATE-002",
        pillar_theme="AI",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        proof_status=ContentIntake.ProofStatus.CONFIRMED,
        status=ContentIntake.Status.ACCEPTED,
    )
    UnblockCondition.objects.create(
        intake=intake,
        condition_type=UnblockCondition.ConditionType.LEGAL_MILESTONE,
        description="Await regulatory sign-off",
        status=UnblockCondition.ConditionStatus.OPEN,
    )
    blocked, reason = check_intake_gate(intake)
    assert blocked is True
    assert "condition" in reason.lower() or "unblock" in reason.lower()


@pytest.mark.django_db
def test_needs_verification_proof_is_blocked(workspace):
    """needs_verification proof_status → (True, reason containing 'proof' or 'verif')."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="GATE-003",
        pillar_theme="Climate",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        proof_status=ContentIntake.ProofStatus.NEEDS_VERIFICATION,
        status=ContentIntake.Status.ACCEPTED,
    )
    blocked, reason = check_intake_gate(intake)
    assert blocked is True
    assert "proof" in reason.lower() or "verif" in reason.lower()


@pytest.mark.django_db
def test_public_safe_no_conditions_is_not_blocked(workspace):
    """public_safe sensitivity + no open conditions → (False, "")."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="GATE-004",
        pillar_theme="Agribusiness",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        proof_status=ContentIntake.ProofStatus.CONFIRMED,
        status=ContentIntake.Status.ACCEPTED,
    )
    blocked, reason = check_intake_gate(intake)
    assert blocked is False
    assert reason == ""
