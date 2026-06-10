"""Tests for check_intake_gate() — intake sensitivity and unblock-condition blocking."""
import pytest

from apps.content_intake.models import ContentIntake, UnblockCondition
from apps.publisher.intake_gate import check_intake_gate


@pytest.mark.django_db
def test_private_hold_blocks_dispatch(workspace, platform_post_factory):
    """private_hold sensitivity → (True, reason containing 'private_hold').

    Also exercises the full dispatch-linkage path: a PlatformPost is created
    and its parent Post is linked to the intake via ContentIntake.post, which
    is the same path the publisher engine traverses when it calls
    check_intake_gate(intake_item) inside _dispatch_to_provider.
    """
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="GATE-001",
        pillar_theme="Energy",
        sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
        status=ContentIntake.Status.ACCEPTED,
    )
    platform_post = platform_post_factory(workspace=workspace)
    # Link the intake to the platform post's parent Post, mirroring the
    # publisher engine's intake_source traversal.
    intake.post = platform_post.post
    intake.save(update_fields=["post"])

    blocked, reason = check_intake_gate(intake)
    assert blocked is True
    assert "private_hold" in reason.lower()


@pytest.mark.django_db
def test_open_conditions_block_dispatch(workspace):
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
        description="MoU not signed",
        status=UnblockCondition.ConditionStatus.OPEN,
    )
    blocked, reason = check_intake_gate(intake)
    assert blocked is True
    assert "unblock" in reason.lower() or "condition" in reason.lower()


@pytest.mark.django_db
def test_needs_verification_proof_blocks(workspace):
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
def test_public_safe_no_conditions_passes(workspace):
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
