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
    assert resp.status_code in (200, 204)
    item.refresh_from_db()
    # is_schedulable is False (open condition), so the "done" branch is gated and
    # the move is a no-op: the status must stay at its prior value (APPROVED),
    # NOT advance to APPROVED-via-the-branch from some other lane. Asserting the
    # exact prior value catches a deleted guard — a vacuous `!= SCHEDULED` would
    # pass even if the block were removed, since the branch never sets SCHEDULED.
    assert item.status == ContentIntake.Status.APPROVED


@pytest.mark.django_db
@pytest.mark.parametrize(
    "terminal_status",
    [
        ContentIntake.Status.SCHEDULED,
        ContentIntake.Status.PUBLISHED,
        ContentIntake.Status.ARCHIVED,
    ],
)
@pytest.mark.parametrize("to_stage", ["todo", "in_progress"])
def test_terminal_item_is_not_demoted_by_lane_drag(authed, workspace, terminal_status, to_stage):
    """A scheduled/published/archived item dragged back to an earlier lane must

    stay put — never silently reverted to accepted/drafting. Guards the
    state-integrity hole where the todo/in_progress branches fired from ANY
    source status.
    """
    item = ContentIntake.objects.create(
        workspace=workspace, external_id=f"T-{terminal_status}-{to_stage}", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=terminal_status,
    )
    url = reverse("console:intake-move-stage", args=[item.pk])
    resp = authed.post(url, {"to_stage": to_stage})
    assert resp.status_code in (200, 204)
    item.refresh_from_db()
    assert item.status == terminal_status  # no-op: terminal item not demoted


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
    # request_herald_draft is mocked True, so this is the success path. 409 is the
    # FAILURE code (non-HX draft failure) — accepting it would let the test pass on
    # a failed draft, so assert only the success codes (204 non-HX, 200 HX render).
    assert resp.status_code in (200, 204)
    draft.assert_called_once()
    ensure.assert_called_once()
