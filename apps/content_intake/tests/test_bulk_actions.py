# apps/content_intake/tests/test_bulk_actions.py
import pytest
from unittest.mock import patch
from django.urls import reverse
from apps.content_intake.models import ContentIntake


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_draft_selected_drafts_each_eligible(authed, workspace):
    a = ContentIntake.objects.create(workspace=workspace, external_id="A", angle="a",
        sensitivity="public_safe", status="accepted")
    b = ContentIntake.objects.create(workspace=workspace, external_id="B", angle="b",
        sensitivity="public_safe", status="accepted")
    url = reverse("console:intake-draft-selected")
    with patch("apps.content_intake.views.request_herald_draft", return_value=True) as m:
        resp = authed.post(url, {"ids": [str(a.pk), str(b.pk)]})
    assert resp.status_code == 200
    assert m.call_count == 2
