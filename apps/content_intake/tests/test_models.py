"""Tests for ContentIntake, UnblockCondition, and IntakeReviewItem models."""

import pytest

from apps.content_intake.models import ContentIntake, IntakeReviewItem, UnblockCondition


@pytest.mark.django_db
def test_intake_with_open_conditions_is_not_schedulable(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-001",
        pillar_theme="Energy",
        angle="Solar growth",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    UnblockCondition.objects.create(
        intake=intake,
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
        description="verify KALRO data",
        status=UnblockCondition.ConditionStatus.OPEN,
    )
    assert intake.is_schedulable is False


@pytest.mark.django_db
def test_private_hold_intake_is_not_schedulable(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-002",
        pillar_theme="AI",
        sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
        status=ContentIntake.Status.ACCEPTED,
    )
    assert intake.is_schedulable is False


@pytest.mark.django_db
def test_public_safe_no_conditions_is_schedulable(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-003",
        pillar_theme="Agribusiness",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    assert intake.is_schedulable is True


@pytest.mark.django_db
def test_example_row_marked_skipped(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-EXAMPLE",
        pillar_theme="",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.SKIPPED,
        skip_reason="example row",
    )
    assert intake.status == ContentIntake.Status.SKIPPED


# ---------------------------------------------------------------------------
# Hard gate: proof_status == NEEDS_VERIFICATION
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_needs_verification_proof_status_is_not_schedulable(workspace):
    """Second hard gate: proof_status=needs_verification blocks scheduling."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-004",
        pillar_theme="Energy",
        angle="Grid stats",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        proof_status=ContentIntake.ProofStatus.NEEDS_VERIFICATION,
        status=ContentIntake.Status.ACCEPTED,
    )
    assert intake.is_schedulable is False


# ---------------------------------------------------------------------------
# UnblockCondition: closed condition does NOT block scheduling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_closed_condition_does_not_block_scheduling(workspace):
    """A CLOSED UnblockCondition must not prevent scheduling."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-005",
        pillar_theme="AI",
        angle="Model benchmarks",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    UnblockCondition.objects.create(
        intake=intake,
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
        description="verify data",
        status=UnblockCondition.ConditionStatus.CLOSED,
    )
    assert intake.is_schedulable is True


# ---------------------------------------------------------------------------
# IntakeReviewItem: creation and resolve flow
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_intake_review_item_created_unresolved(workspace):
    """A new IntakeReviewItem starts unresolved with no resolved_by."""
    item = IntakeReviewItem.objects.create(
        workspace=workspace,
        external_id="ROW-BAD-01",
        raw_row={"pillar_theme": "", "sensitivity": "??"},
        reason=IntakeReviewItem.ReviewReason.SENSITIVITY_UNRECOGNIZED,
        detail="unrecognized value: '??'",
    )
    assert item.resolved is False
    assert item.resolved_by_id is None
    assert item.resolved_at is None


@pytest.mark.django_db
def test_intake_review_item_resolve_flow(workspace, django_user_model):
    """Marking an IntakeReviewItem resolved records the resolver and timestamp."""
    from django.utils import timezone

    reviewer = django_user_model.objects.create_user(
        email="reviewer@example.com", password="x"
    )
    item = IntakeReviewItem.objects.create(
        workspace=workspace,
        external_id="",
        raw_row={"status": "unknown"},
        reason=IntakeReviewItem.ReviewReason.STATUS_UNMAPPED,
    )

    now = timezone.now()
    item.resolved = True
    item.resolved_by = reviewer
    item.resolved_at = now
    item.save()

    item.refresh_from_db()
    assert item.resolved is True
    assert item.resolved_by == reviewer
    assert item.resolved_at == now
