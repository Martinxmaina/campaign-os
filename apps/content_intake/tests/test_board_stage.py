import pytest
from apps.content_intake.models import ContentIntake

@pytest.mark.django_db
@pytest.mark.parametrize("status,expected", [
    ("idea", "todo"), ("accepted", "todo"), ("held", "todo"), ("blocked", "todo"),
    ("drafting", "in_progress"), ("in_review", "in_progress"), ("approved", "in_progress"),
    ("scheduled", "done"), ("published", "done"), ("archived", "done"),
])
def test_board_stage(workspace, status, expected):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id=f"S-{status}", status=status,
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
    )
    assert item.board_stage == expected
