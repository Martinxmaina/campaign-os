"""Tests for content_intake views (T9)."""

import pytest
from django.urls import reverse

from apps.content_intake.models import ContentIntake, UnblockCondition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def intake_item(db, workspace):
    """A basic ContentIntake item scoped to the test workspace."""
    return ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-V01",
        pillar_theme="Climate Finance",
        angle="Green bonds surge",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )


@pytest.fixture
def authenticated_client(client, db, workspace):
    """A Django test client logged in as a user who is a member of *workspace*."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    user = User.objects.create_user(
        email="boarduser@example.com",
        password="testpass123",
        name="Board User",
        tos_accepted_at=timezone.now(),
    )
    # Org membership
    OrgMembership.objects.create(
        user=user,
        organization=workspace.organization,
        org_role=OrgMembership.OrgRole.OWNER,
    )
    # Workspace membership so RBACMiddleware sets request.workspace
    WorkspaceMembership.objects.create(
        user=user,
        workspace=workspace,
        workspace_role="manager",
    )
    # Set last_workspace_id so the middleware resolves it for non-workspace-URL paths
    user.last_workspace_id = workspace.id
    user.save(update_fields=["last_workspace_id"])

    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# Tests (spec-compliant names — Task 9)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_intake_board_requires_login(client, workspace):
    """Unauthenticated GET /console/intake/ must redirect (302) to login."""
    url = reverse("content_intake:board")
    response = client.get(url)
    assert response.status_code == 302
    assert "/accounts/" in response.url or "login" in response.url.lower()


@pytest.mark.django_db
def test_intake_board_shows_items(authenticated_client, intake_item):
    """Authenticated GET /console/intake/ must include the item's pillar_theme."""
    url = reverse("content_intake:board")
    response = authenticated_client.get(url)
    assert response.status_code == 200
    assert b"Climate Finance" in response.content


@pytest.mark.django_db
def test_intake_board_filter_by_status(authenticated_client, workspace, intake_item):
    """GET /console/intake/?status=idea must return 200 (filter works)."""
    # Create an extra item with a different status to ensure filtering is exercised
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-V02",
        pillar_theme="Energy Storage",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.IDEA,
    )
    url = reverse("content_intake:board") + "?status=idea"
    response = authenticated_client.get(url)
    assert response.status_code == 200
    # Pillar of the *idea* item should appear; *accepted* item should not
    assert b"Energy Storage" in response.content
    assert b"Climate Finance" not in response.content


@pytest.mark.django_db
def test_close_condition_marks_closed(authenticated_client, intake_item):
    """POST to close_condition must set status=closed and persist evidence_note."""
    condition = UnblockCondition.objects.create(
        intake=intake_item,
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
        description="Verify KALRO data",
        status=UnblockCondition.ConditionStatus.OPEN,
    )
    url = reverse(
        "content_intake:close_condition",
        kwargs={"condition_pk": condition.pk},
    )
    response = authenticated_client.post(url, {"evidence_note": "Verified via email"})
    # Non-HTMX: expect 204
    assert response.status_code == 204

    condition.refresh_from_db()
    assert condition.status == UnblockCondition.ConditionStatus.CLOSED
    assert condition.evidence_note == "Verified via email"
    assert condition.closed_by is not None
    assert condition.closed_at is not None
