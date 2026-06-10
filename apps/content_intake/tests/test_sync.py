"""Tests for apps/content_intake/sheets_sync.py.

All tests mock _get_sheet_rows to avoid any network calls.  The DB is
exercised via pytest-django's @pytest.mark.django_db.

SAMPLE_ROWS structure (index → column label):
  0  external_id
  1  pillar_theme
  2  angle
  3  proof_point
  4  status
  5  sensitivity
  6  channels
  7  priority
  8  campaign
  9  house
  10 owner_raw
  11 submitted_by_raw
  12 target_date
  13 notes
  14 ref_links
  15 skip_reason
"""

from unittest.mock import patch

import pytest

from apps.content_intake.models import ContentIntake, IntakeReviewItem, UnblockCondition

# ---------------------------------------------------------------------------
# Fixtures: shared row data
# ---------------------------------------------------------------------------

HEADER_ROW = [
    "ID", "Pillar/Theme", "Angle", "Proof Point", "Status", "Sensitivity",
    "Channels", "Priority", "Campaign", "House", "Owner", "Submitted By",
    "Target Date", "Notes", "Ref Links", "Skip Reason",
]

# A template/sentinel row that must be silently ignored
EXAMPLE_ROW = [
    "EXAMPLE", "EXAMPLE", "Sample angle", "Sample proof",
    "Idea", "Public safe", "LinkedIn", "M", "Campaign A",
    "WAIIS", "Martin", "Joseph", "2025-06-01", "", "", "",
]

# A clean, fully-valid real row
REAL_ROW_001 = [
    "ROW-001", "Energy", "Solar growth story", "IRENA report 2024",
    "Accepted", "Public safe", "LinkedIn WAIIS", "H", "EGM 2025",
    "WAIIS", "Martin", "Joseph", "2025-06-15",
    "Good to go", "https://irena.org", "",
]

# A row with unrecognized sensitivity — should go to review queue
BAD_SENSITIVITY_ROW = [
    "ROW-002", "Climate", "Carbon markets explainer", "UNFCCC data",
    "Drafting", "mega-private-ultra",  # unrecognized sensitivity
    "Newsletter", "M", "EGM 2025",
    "WAIIS", "Martin", "Joseph", "2025-06-20",
    "verify source before publishing",  # triggers source_verification condition
    "", "",
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
    # Only include header + real row to isolate this test
    rows = [HEADER_ROW, REAL_ROW_001]
    with patch(MODULE_PATH, return_value=rows):
        from apps.content_intake.sheets_sync import sync_sheet_to_intake
        stats = sync_sheet_to_intake(workspace)

    assert stats["created"] == 1
    assert stats["errors"] == 0

    obj = ContentIntake.objects.get(workspace=workspace, external_id="ROW-001")
    assert obj.pillar_theme == "Energy"
    assert obj.sensitivity == "public_safe"
    assert obj.status == "accepted"
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

    # BAD_SENSITIVITY_ROW notes = "verify source before publishing"
    # → extract_unblock_conditions should yield source_verification
    source_cond = conditions.filter(
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION
    )
    assert source_cond.exists(), (
        "source_verification condition should have been created from "
        "'verify source before publishing' note"
    )
    assert source_cond.first().status == "open"
