"""Tests for the 14-day calendar gap scanner (calendar_agent.py)."""
from __future__ import annotations

import pytest
from datetime import date, timedelta

from apps.content_intake.models import ContentIntake, UnblockCondition


@pytest.mark.django_db
def test_scan_14day_gaps_returns_list(workspace):
    """scan_14day_gaps must return a list (possibly empty) for any workspace."""
    from apps.content_intake.calendar_agent import scan_14day_gaps

    result = scan_14day_gaps(workspace)
    assert isinstance(result, list)


@pytest.mark.django_db
def test_blocked_items_not_proposed(workspace):
    """Items with open unblock conditions must not appear in proposals."""
    from apps.content_intake.calendar_agent import scan_14day_gaps

    blocked = ContentIntake.objects.create(
        workspace=workspace,
        external_id="BLOCKED-001",
        pillar_theme="Energy",
        angle="Grid upgrade",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
        priority=ContentIntake.Priority.HIGH,
    )
    UnblockCondition.objects.create(
        intake=blocked,
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
        description="verify source data",
        status=UnblockCondition.ConditionStatus.OPEN,
    )

    proposals = scan_14day_gaps(workspace)
    proposed_ids = {p["external_id"] for p in proposals}
    assert "BLOCKED-001" not in proposed_ids


@pytest.mark.django_db
def test_scan_respects_target_publish_date(workspace):
    """An item with a future target_publish_date must not be proposed before that date."""
    from apps.content_intake.calendar_agent import scan_14day_gaps

    # Create an item whose target date is 13 days from now (within the 14-day window
    # but definitely not today).
    future_date = date.today() + timedelta(days=13)
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="FUTURE-001",
        pillar_theme="Climate",
        angle="Green bonds",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
        priority=ContentIntake.Priority.HIGH,
        target_publish_date=future_date,
    )

    proposals = scan_14day_gaps(workspace)

    # Filter proposals for this item
    future_proposals = [p for p in proposals if p["external_id"] == "FUTURE-001"]

    # Every proposal for this item must be on or after the target_publish_date
    for proposal in future_proposals:
        proposed = date.fromisoformat(proposal["proposed_date"])
        assert proposed >= future_date, (
            f"Item FUTURE-001 was proposed on {proposed} but target_publish_date is {future_date}"
        )
