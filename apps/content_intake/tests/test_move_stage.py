from unittest.mock import patch
import pytest
from django.urls import reverse
from apps.content_intake.models import ContentIntake


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    # RBACMiddleware resolves request.workspace for these non-workspace_id intake
    # URLs (/console/intake/<intake_pk>/...) via user.last_workspace_id. The
    # accounts post_save signal seeds a separate singleton workspace on user
    # creation, so point last_workspace_id at this workspace explicitly for the
    # membership above to take effect (mirrors test_board_views.authed).
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_move_to_in_progress_only_changes_status_never_drafts(authed, workspace):
    """Moving a card must NOT trigger HERALD — drafting is manual only."""
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="M-1", angle="Solar",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
    )
    url = reverse("console:intake-move-stage", args=[item.pk])
    with patch("apps.content_intake.views.request_herald_draft") as draft:
        resp = authed.post(url, {"to_stage": "in_progress"})
    assert resp.status_code in (200, 204)
    draft.assert_not_called()          # ← stage change must never auto-draft
    item.refresh_from_db()
    assert item.status == ContentIntake.Status.DRAFTING


@pytest.mark.django_db
def test_move_to_todo_reverts_status(authed, workspace):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="M-2", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.DRAFTING,
    )
    url = reverse("console:intake-move-stage", args=[item.pk])
    resp = authed.post(url, {"to_stage": "todo"})
    assert resp.status_code in (200, 204)
    item.refresh_from_db()
    assert item.status == ContentIntake.Status.ACCEPTED


@pytest.mark.django_db
def test_move_blocked_item_to_done_is_rejected(authed, workspace):
    from apps.content_intake.models import UnblockCondition
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="M-3", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.APPROVED,
    )
    UnblockCondition.objects.create(intake=item, condition_type="legal_milestone",
        description="MoU", status="open")
    url = reverse("console:intake-move-stage", args=[item.pk])
    resp = authed.post(url, {"to_stage": "done"})
    item.refresh_from_db()
    assert item.status != ContentIntake.Status.SCHEDULED


@pytest.mark.django_db
def test_manual_draft_now_drafts_and_creates_post(authed, workspace):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="D-1", angle="Solar",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
    )
    url = reverse("console:intake-draft-now", args=[item.pk])
    with patch("apps.content_intake.views.request_herald_draft", return_value=True) as draft, \
         patch("apps.content_intake.views.ensure_draft_post") as ensure:
        resp = authed.post(url)
    assert resp.status_code in (200, 204, 409)
    draft.assert_called_once()
    ensure.assert_called_once()
