"""Tests for content_intake views (T9)."""

import pytest
from django.urls import reverse

from apps.content_intake.models import ContentIntake, UnblockCondition
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


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
    url = reverse("console:intake-board")
    response = client.get(url)
    assert response.status_code == 302
    assert "/login" in response["Location"] or "/accounts" in response["Location"]


@pytest.mark.django_db
def test_intake_board_shows_items(authenticated_client, intake_item):
    """Authenticated GET /console/intake/ must include the item's pillar_theme."""
    url = reverse("console:intake-board")
    response = authenticated_client.get(url)
    assert response.status_code == 200
    assert b"Climate Finance" in response.content


@pytest.mark.django_db
def test_intake_board_filter_by_status(authenticated_client, workspace, intake_item):
    """Status filter must show matching items and hide non-matching ones.

    Uses ``angle`` as the per-card discriminator because ``pillar_theme`` also
    appears in the filter <select> dropdown for all workspace items, which
    would make a raw-content search ambiguous.
    """
    # intake_item has status=accepted, angle="Green bonds surge"
    # Create a second item with status=idea and a distinct angle
    idea_item = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-V02",
        pillar_theme="Renewable Energy",
        angle="Solar push unique",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.IDEA,
    )

    url = reverse("console:intake-board")

    # Filter by 'idea' — idea_item card must be present, intake_item card absent
    response = authenticated_client.get(url + "?status=idea")
    assert response.status_code == 200
    assert idea_item.angle.encode() in response.content
    assert intake_item.angle.encode() not in response.content

    # Filter by 'accepted' — intake_item card must be present, idea_item card absent
    response = authenticated_client.get(url + "?status=accepted")
    assert response.status_code == 200
    assert intake_item.angle.encode() in response.content
    assert idea_item.angle.encode() not in response.content


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
        "console:intake-close-condition",
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


@pytest.mark.django_db
def test_intake_board_invalid_status_filter_ignored(authenticated_client, intake_item):
    """An invalid ?status= value must not filter results — it is silently ignored.

    Previously the unsanitized string was passed directly to the ORM, returning
    an empty queryset without any error, and exposing status enum names as an
    oracle. After the fix, unrecognised values are discarded and all items are
    returned.
    """
    url = reverse("console:intake-board")
    response = authenticated_client.get(url + "?status=__invalid__")
    assert response.status_code == 200
    # The intake_item should still appear because the filter was discarded.
    assert intake_item.angle.encode() in response.content


@pytest.mark.django_db
def test_intake_board_renders_activity_badge(authenticated_client, workspace, intake_item):
    """The activity badge must be wired into the board and reflect the most
    recent sheet-sync and HERALD-draft timestamps for the workspace.

    Regression guard: the _activity_badge.html partial was previously created
    but never included by any template and fed no context, making it dead code.
    """
    from django.utils import timezone

    intake_item.last_synced_at = timezone.now()
    intake_item.herald_drafted_at = timezone.now()
    intake_item.save(update_fields=["last_synced_at", "herald_drafted_at"])

    url = reverse("console:intake-board")
    response = authenticated_client.get(url)
    assert response.status_code == 200
    # The badge labels (only emitted when the timestamps are present) prove the
    # partial is included AND that the view supplies the context.
    assert b"Sheet synced:" in response.content
    assert b"HERALD drafted:" in response.content


@pytest.mark.django_db
def test_close_condition_cross_workspace_isolation(client, db, workspace):
    """A user authenticated in workspace A must not be able to close a condition
    belonging to workspace B (cross-tenant isolation).

    The ``intake__workspace=request.workspace`` guard in get_object_or_404 is
    the only line of defence; this test verifies it is effective.
    """
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    # --- workspace A setup (the client's workspace) ---
    user_a = User.objects.create_user(
        email="user_a@example.com",
        password="testpass123",
        name="User A",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(
        user=user_a,
        organization=workspace.organization,
        org_role=OrgMembership.OrgRole.OWNER,
    )
    WorkspaceMembership.objects.create(
        user=user_a,
        workspace=workspace,
        workspace_role="manager",
    )
    user_a.last_workspace_id = workspace.id
    user_a.save(update_fields=["last_workspace_id"])

    # --- workspace B setup (a completely separate tenant) ---
    org_b = Organization.objects.create(name="Other Org")
    workspace_b = Workspace.objects.create(organization=org_b, name="Other WS")

    intake_b = ContentIntake.objects.create(
        workspace=workspace_b,
        external_id="ROW-B01",
        pillar_theme="Other Theme",
        angle="Should not be accessible",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    condition_b = UnblockCondition.objects.create(
        intake=intake_b,
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
        description="Workspace B condition",
        status=UnblockCondition.ConditionStatus.OPEN,
    )

    # Log in as user_a (scoped to workspace A) and try to close workspace B's condition.
    client.force_login(user_a)
    url = reverse(
        "console:intake-close-condition",
        kwargs={"condition_pk": condition_b.pk},
    )
    response = client.post(url, {"evidence_note": "Cross-tenant attack"})

    # The request.workspace (workspace A) does not match condition_b's workspace,
    # so get_object_or_404 must return 404.
    assert response.status_code == 404

    # Verify the condition was NOT mutated.
    condition_b.refresh_from_db()
    assert condition_b.status == UnblockCondition.ConditionStatus.OPEN


@pytest.mark.django_db
def test_draft_now_calls_herald(authenticated_client, intake_item):
    from unittest.mock import patch

    intake_item.status = "accepted"
    intake_item.sensitivity = "public_safe"
    intake_item.save()
    url = reverse("console:intake-draft-now", args=[intake_item.pk])
    with patch("apps.content_intake.views.request_herald_draft", return_value=True) as m:
        resp = authenticated_client.post(url)
    # Non-HX happy path: 204 No Content.
    assert resp.status_code == 204
    m.assert_called_once()


@pytest.mark.django_db
def test_draft_now_non_hx_failure_returns_409(authenticated_client, intake_item):
    """Non-HX path: a failed HERALD draft request must surface as HTTP 409."""
    from unittest.mock import patch

    intake_item.status = "accepted"
    intake_item.sensitivity = "public_safe"
    intake_item.save()
    url = reverse("console:intake-draft-now", args=[intake_item.pk])
    with patch("apps.content_intake.views.request_herald_draft", return_value=False) as m:
        resp = authenticated_client.post(url)
    assert resp.status_code == 409
    m.assert_called_once()


@pytest.mark.django_db
def test_draft_now_hx_success_rerenders_card_as_drafting(authenticated_client, intake_item):
    """HX path success: the card re-renders, the Draft button is gone, and the
    item reflects the ``drafting`` status that ``request_herald_draft`` set.

    The view re-renders ``item`` *after* the bridge mutated it in place, so to
    exercise the real template branch we mutate the same instance the view will
    receive. We assert the button (whose presence is gated on
    status==accepted) is absent.
    """
    from unittest.mock import patch

    intake_item.status = "accepted"
    intake_item.sensitivity = "public_safe"
    intake_item.save()
    url = reverse("console:intake-draft-now", args=[intake_item.pk])

    def _fake_draft(item):
        item.status = ContentIntake.Status.DRAFTING
        item.save(update_fields=["status"])
        return True

    with patch("apps.content_intake.views.request_herald_draft", side_effect=_fake_draft):
        resp = authenticated_client.post(url, HTTP_HX_REQUEST="true")

    assert resp.status_code == 200
    # The card partial is returned (its id is present)...
    assert f"intake-card-{intake_item.pk}".encode() in resp.content
    # ...but the "Draft with HERALD" button is hidden now that status=drafting.
    assert b"Draft with HERALD" not in resp.content


@pytest.mark.django_db
def test_draft_now_hx_failure_surfaces_error_not_silent_noop(authenticated_client, intake_item):
    """HX path failure must NOT look like a successful no-op.

    Previously the view re-rendered the unchanged ``_card.html`` with HTTP 200,
    so a failed request appeared identical to success. The fix returns a visible
    error partial retargeted into the card via HX-Retarget/HX-Reswap. We assert
    the error banner is present, the card is NOT re-rendered (no card id), and
    the HTMX retarget headers point at the card error region.
    """
    from unittest.mock import patch

    intake_item.status = "accepted"
    intake_item.sensitivity = "public_safe"
    intake_item.save()
    url = reverse("console:intake-draft-now", args=[intake_item.pk])

    with patch("apps.content_intake.views.request_herald_draft", return_value=False) as m:
        resp = authenticated_client.post(url, HTTP_HX_REQUEST="true")

    m.assert_called_once()
    # Visible, actionable error feedback is returned to the user.
    assert b"HERALD couldn't draft" in resp.content
    # It is an error region, NOT a silent re-render of the (unchanged) card.
    assert f"intake-card-{intake_item.pk}".encode() not in resp.content
    # HTMX is told to place the banner into the card error region.
    assert resp["HX-Retarget"] == f"#intake-card-{intake_item.pk}"
    assert resp["HX-Reswap"] == "afterbegin"


@pytest.mark.django_db
def test_draft_now_cross_workspace_isolation(client, db, workspace):
    """A user scoped to workspace A must not be able to trigger a draft for an
    intake item belonging to workspace B (cross-tenant isolation, 404)."""
    from unittest.mock import patch

    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    # --- workspace A (the client's workspace) ---
    user_a = User.objects.create_user(
        email="draft_user_a@example.com",
        password="testpass123",
        name="Draft User A",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(
        user=user_a,
        organization=workspace.organization,
        org_role=OrgMembership.OrgRole.OWNER,
    )
    WorkspaceMembership.objects.create(
        user=user_a,
        workspace=workspace,
        workspace_role="manager",
    )
    user_a.last_workspace_id = workspace.id
    user_a.save(update_fields=["last_workspace_id"])

    # --- workspace B (separate tenant) ---
    org_b = Organization.objects.create(name="Draft Other Org")
    workspace_b = Workspace.objects.create(organization=org_b, name="Draft Other WS")
    intake_b = ContentIntake.objects.create(
        workspace=workspace_b,
        external_id="ROW-DB01",
        pillar_theme="Other Theme",
        angle="Cross-tenant draft target",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )

    client.force_login(user_a)
    url = reverse("console:intake-draft-now", args=[intake_b.pk])
    with patch("apps.content_intake.views.request_herald_draft", return_value=True) as m:
        resp = client.post(url)

    # The intake__workspace guard must yield 404 and HERALD must NOT be called.
    assert resp.status_code == 404
    m.assert_not_called()
