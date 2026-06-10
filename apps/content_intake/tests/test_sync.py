"""Tests for apps/content_intake/sheets_sync.py.

All tests mock _get_sheet_rows to avoid any network calls.  The DB is
exercised via pytest-django's @pytest.mark.django_db.

SAMPLE_ROWS structure matches the spec's prescribed column order (0-based):
  0  ID
  1  Date added
  2  Submitted by
  3  Pillar/Theme
  4  Angle
  5  Proof point
  6  Target audience
  7  Sensitivity flag
  8  Channel
  9  Campaign
  10 Priority
  11 Status
  12 Owner
  13 Target publish date
  14 Notes
  15 Doc links
"""

from unittest.mock import patch

import pytest

from apps.content_intake.models import ContentIntake, IntakeReviewItem, UnblockCondition

# ---------------------------------------------------------------------------
# Fixtures: shared row data
# ---------------------------------------------------------------------------

HEADER_ROW = [
    "ID", "Date added", "Submitted by", "Pillar/Theme", "Angle", "Proof point",
    "Target audience", "Sensitivity flag", "Channel", "Campaign", "Priority",
    "Status", "Owner", "Target publish date", "Notes", "Doc links",
]

# A template/sentinel row that must be silently ignored
EXAMPLE_ROW = [
    "EXAMPLE", "2026-01-01", "Admin", "EXAMPLE", "EXAMPLE", "EXAMPLE",
    "EXAMPLE", "Public", "LinkedIn", "", "M", "Idea", "", "", "EXAMPLE row", "",
]

# A clean, fully-valid real row
REAL_ROW_001 = [
    "ROW-001", "2026-06-01", "Lazarus", "Energy", "Solar growth in EA",
    "IEA 2024 report", "Policy makers", "Public-safe", "LinkedIn (WAIIS page)",
    "WAIIS", "H", "Idea", "Lazarus", "2026-06-15", "", "",
]

# A row with unrecognized sensitivity — should go to review queue
BAD_SENSITIVITY_ROW = [
    "ROW-002", "2026-06-02", "Nduta", "AI", "AI 10Bn thesis",
    "tbd", "VCs", "weird unclear", "Twitter",
    "AI10Bn", "M", "Idea", "Nduta", "", "verify source before posting", "",
]

SAMPLE_ROWS = [HEADER_ROW, EXAMPLE_ROW, REAL_ROW_001, BAD_SENSITIVITY_ROW]

MODULE_PATH = "apps.content_intake.sheets_sync._get_sheet_rows"


# ---------------------------------------------------------------------------
# Test 1: EXAMPLE rows are silently skipped
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_skips_example_rows(workspace):
    with patch(MODULE_PATH, return_value=SAMPLE_ROWS):
        from apps.content_intake.sheets_sync import sync_sheet_to_intake
        stats = sync_sheet_to_intake(workspace)

    assert stats["skipped"] >= 1
    assert not ContentIntake.objects.filter(
        workspace=workspace, external_id="EXAMPLE"
    ).exists()


# ---------------------------------------------------------------------------
# Test 2: Real row is created with correct fields
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_creates_real_row(workspace):
    rows = [HEADER_ROW, REAL_ROW_001]
    with patch(MODULE_PATH, return_value=rows):
        from apps.content_intake.sheets_sync import sync_sheet_to_intake
        stats = sync_sheet_to_intake(workspace)

    assert stats["created"] == 1
    assert stats["errors"] == 0

    obj = ContentIntake.objects.get(workspace=workspace, external_id="ROW-001")
    assert obj.pillar_theme == "Energy"
    assert obj.sensitivity == "public_safe"
    assert obj.status == "idea"
    assert obj.priority == "H"


# ---------------------------------------------------------------------------
# Test 3: Bad sensitivity row lands in review queue
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_bad_sensitivity_goes_to_review_queue(workspace):
    rows = [HEADER_ROW, BAD_SENSITIVITY_ROW]
    with patch(MODULE_PATH, return_value=rows):
        from apps.content_intake.sheets_sync import sync_sheet_to_intake
        stats = sync_sheet_to_intake(workspace)

    assert stats["review_queue"] >= 1

    review = IntakeReviewItem.objects.filter(
        workspace=workspace, external_id="ROW-002"
    )
    assert review.exists(), "IntakeReviewItem should have been created for ROW-002"
    assert review.first().reason == "sensitivity_unrecognized"

    # The ContentIntake record is still created, but sensitivity is private_hold
    intake = ContentIntake.objects.get(workspace=workspace, external_id="ROW-002")
    assert intake.sensitivity == "private_hold"


# ---------------------------------------------------------------------------
# Test 4: Idempotency — second sync of same rows is a no-op
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_idempotent_same_hash_no_update(workspace):
    rows = [HEADER_ROW, REAL_ROW_001]
    with patch(MODULE_PATH, return_value=rows):
        from apps.content_intake.sheets_sync import sync_sheet_to_intake
        first = sync_sheet_to_intake(workspace)

    assert first["created"] == 1

    # Run a second time with identical rows
    with patch(MODULE_PATH, return_value=rows):
        from apps.content_intake.sheets_sync import sync_sheet_to_intake as sync2
        second = sync2(workspace)

    assert second["created"] == 0
    assert second["updated"] == 0
    assert second["skipped"] >= 1  # hash matched → skipped


# ---------------------------------------------------------------------------
# Test 5: UnblockConditions are created from notes field
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_creates_unblock_conditions(workspace):
    rows = [HEADER_ROW, BAD_SENSITIVITY_ROW]
    with patch(MODULE_PATH, return_value=rows):
        from apps.content_intake.sheets_sync import sync_sheet_to_intake
        sync_sheet_to_intake(workspace)

    intake = ContentIntake.objects.get(workspace=workspace, external_id="ROW-002")
    conditions = UnblockCondition.objects.filter(intake=intake)

    # BAD_SENSITIVITY_ROW notes = "verify source before posting"
    # → extract_unblock_conditions should yield source_verification
    source_cond = conditions.filter(
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION
    )
    assert source_cond.exists(), (
        "source_verification condition should have been created from "
        "'verify source before posting' note"
    )
    assert source_cond.first().status == "open"
