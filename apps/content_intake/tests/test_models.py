"""Tests for ContentIntake, UnblockCondition, and IntakeReviewItem models."""

import pytest

from apps.content_intake.models import ContentIntake, UnblockCondition


class TestContentIntakeSchedulability:
    """is_schedulable / has_open_conditions gate logic."""

    def test_private_hold_is_not_schedulable(self, workspace, db):
        """An item with sensitivity=private_hold must not be schedulable."""
        item = ContentIntake.objects.create(
            workspace=workspace,
            external_id="PRIV-001",
            pillar_theme="Energy",
            sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
            status=ContentIntake.Status.ACCEPTED,
        )
        assert item.is_schedulable is False

    def test_open_unblock_conditions_block_scheduling(self, intake_item, db):
        """An item with an open UnblockCondition must not be schedulable."""
        assert intake_item.sensitivity == ContentIntake.Sensitivity.PUBLIC_SAFE
        # Precondition: schedulable without conditions
        assert intake_item.is_schedulable is True

        UnblockCondition.objects.create(
            intake=intake_item,
            condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
            description="Needs source URL confirmed",
            status=UnblockCondition.ConditionStatus.OPEN,
        )

        # Refresh from DB to ensure the queryset picks up the new condition
        intake_item.refresh_from_db()
        assert intake_item.has_open_conditions is True
        assert intake_item.is_schedulable is False

    def test_public_safe_no_conditions_is_schedulable(self, intake_item, db):
        """An item with public_safe sensitivity and no open conditions is schedulable."""
        assert intake_item.sensitivity == ContentIntake.Sensitivity.PUBLIC_SAFE
        assert intake_item.has_open_conditions is False
        assert intake_item.is_schedulable is True

    def test_skipped_row_has_status_skipped(self, workspace, db):
        """A row explicitly marked skipped carries status=skipped."""
        item = ContentIntake.objects.create(
            workspace=workspace,
            external_id="SKIP-001",
            pillar_theme="Climate",
            sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
            status=ContentIntake.Status.SKIPPED,
            skip_reason="Out of scope for this campaign cycle",
        )
        assert item.status == ContentIntake.Status.SKIPPED
        assert item.skip_reason != ""
