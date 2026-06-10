"""Tests for agent_context.build_intake_context."""
import datetime

import pytest

from apps.content_intake.agent_context import build_intake_context
from apps.content_intake.models import ContentIntake


@pytest.mark.django_db
def test_context_includes_accepted_public_safe_items(workspace):
    """Accepted, public_safe items must appear in the agent context."""
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-AC-001",
        pillar_theme="Energy",
        angle="Solar growth in East Africa",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
        priority=ContentIntake.Priority.HIGH,
    )
    ctx = build_intake_context(workspace)
    assert ctx["total_visible"] == 1
    assert len(ctx["intake_items"]) == 1
    item = ctx["intake_items"][0]
    assert item["external_id"] == "ROW-AC-001"
    assert item["sensitivity"] == "public_safe"
    assert item["priority"] == "H"
    assert ctx["workspace"] == str(workspace.pk)


@pytest.mark.django_db
def test_context_excludes_private_hold_items(workspace):
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
def test_submitted_items_have_priority_weight_key(workspace):
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
def test_items_with_target_publish_date_include_iso_format(workspace):
    """Items with a target_publish_date must expose it as an ISO-format string."""
    pub_date = datetime.date(2026, 7, 15)
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-DATE-001",
        pillar_theme="Climate",
        angle="Nairobi summit preview",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
        target_publish_date=pub_date,
    )
    # Also create an item without a date to confirm None handling
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-DATE-002",
        pillar_theme="Energy",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.IDEA,
        target_publish_date=None,
    )
    ctx = build_intake_context(workspace)
    by_id = {i["external_id"]: i for i in ctx["intake_items"]}
    assert by_id["ROW-DATE-001"]["target_publish_date"] == "2026-07-15"
    assert by_id["ROW-DATE-002"]["target_publish_date"] is None
