from unittest.mock import patch
import pytest
from apps.content_intake.models import ContentIntake
from apps.content_intake.tasks import request_herald_drafts_for_workspace


@pytest.mark.django_db
def test_drafts_only_eligible_items(workspace):
    ContentIntake.objects.create(
        workspace=workspace, external_id="A",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="a",
    )
    ContentIntake.objects.create(
        workspace=workspace, external_id="B",
        sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
        status=ContentIntake.Status.ACCEPTED, angle="b",
    )
    ContentIntake.objects.create(
        workspace=workspace, external_id="C",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.IDEA, angle="c",
    )
    with patch("apps.content_intake.tasks.request_herald_draft", return_value=True) as m:
        result = request_herald_drafts_for_workspace(str(workspace.pk))
    # Only item A is eligible (accepted + public_safe)
    assert m.call_count == 1
    assert result["drafted"] == 1


@pytest.mark.django_db
def test_sets_last_draft_cache(workspace):
    from django.core.cache import cache
    ContentIntake.objects.create(
        workspace=workspace, external_id="A",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="a",
    )
    with patch("apps.content_intake.tasks.request_herald_draft", return_value=True):
        request_herald_drafts_for_workspace(str(workspace.pk))
    assert cache.get(f"intake:last_draft:{workspace.pk}") is not None
