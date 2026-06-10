"""Tests for agent_context.build_intake_context."""
import datetime

import pytest

from apps.content_intake.agent_context import build_intake_context
from apps.content_intake.models import ContentIntake


@pytest.mark.django_db
def test_context_includes_accepted_items(workspace, intake_item):
    """Accepted, public_safe items must appear in the agent context with correct fields."""
    ctx = build_intake_context(workspace)
    assert ctx["total_visible"] == 1
    assert ctx["workspace"] == str(workspace.pk)
    item = next((i for i in ctx["intake_items"] if i["external_id"] == intake_item.external_id), None)
    assert item is not None, f"expected {intake_item.external_id!r} in context"
    assert item["sensitivity"] == "public_safe"
    assert item["priority"] == "H"


@pytest.mark.django_db
def test_context_excludes_private_hold(workspace):
    """private_hold items must NEVER appear in agent context."""
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-PH-001",
        pillar_theme="Legal",
        angle="Confidential partnership deal",
        sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
        status=ContentIntake.Status.ACCEPTED,
    )
    # Also create one visible item to confirm the filter is discriminating
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-PH-002",
        pillar_theme="Energy",
        angle="Public solar update",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.IDEA,
    )
    ctx = build_intake_context(workspace)
    external_ids = [i["external_id"] for i in ctx["intake_items"]]
    assert "ROW-PH-001" not in external_ids
    assert "ROW-PH-002" in external_ids
    assert ctx["total_visible"] == 1


@pytest.mark.django_db
def test_context_submitted_ideas_get_priority_boost(workspace):
    """Every item in the context must include a priority_weight key."""
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-PW-001",
        pillar_theme="AI",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING,
        priority=ContentIntake.Priority.HIGH,
    )
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-PW-002",
        pillar_theme="Climate",
        sensitivity=ContentIntake.Sensitivity.PARTNER_ONLY,
        status=ContentIntake.Status.IDEA,
        priority=ContentIntake.Priority.MEDIUM,
    )
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-PW-003",
        pillar_theme="Agri",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
        priority=ContentIntake.Priority.LOW,
    )
    ctx = build_intake_context(workspace)
    assert ctx["total_visible"] == 3
    weights = {i["external_id"]: i["priority_weight"] for i in ctx["intake_items"]}
    assert weights["ROW-PW-001"] == 3  # H → 3
    assert weights["ROW-PW-002"] == 2  # M → 2
    assert weights["ROW-PW-003"] == 1  # L → 1


@pytest.mark.django_db
def test_context_includes_target_dates(workspace, intake_item_with_date):
    """Items with a target_publish_date must expose it as an ISO-format string."""
    ctx = build_intake_context(workspace)
    item = next(
        (i for i in ctx["intake_items"] if i["external_id"] == intake_item_with_date.external_id),
        None,
    )
    assert item is not None
    date_val = item["target_publish_date"]
    assert isinstance(date_val, str), f"expected str, got {type(date_val)}"
    assert date_val == intake_item_with_date.target_publish_date.isoformat(), (
        f"date mismatch: got {date_val!r}, expected {intake_item_with_date.target_publish_date.isoformat()!r}"
    )
