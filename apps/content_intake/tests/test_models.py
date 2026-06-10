"""Tests for ContentIntake, UnblockCondition, and IntakeReviewItem models."""

import pytest

from apps.content_intake.models import ContentIntake, UnblockCondition


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
