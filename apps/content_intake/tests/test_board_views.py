import pytest
from django.urls import reverse
from apps.content_intake.models import ContentIntake


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    # RBACMiddleware resolves request.workspace for non-workspace_id URLs (the
    # intake board uses /intake/<intake_pk>/...) via user.last_workspace_id, so
    # point it at this workspace. The accounts post_save signal seeds a separate
    # singleton workspace on user creation, so we must overwrite it explicitly
    # for the membership above to take effect.
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_row_panel_renders_doc_chips(authed, workspace):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="P-1", pillar_theme="Energy", angle="Solar",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
        reference_links=[{"title": "Brief", "url": "https://docs.google.com/document/d/z/edit", "type": "gdoc"}],
    )
    url = reverse("console:intake-row-panel", args=[item.pk])
    resp = authed.get(url)
    assert resp.status_code == 200
    assert b"Brief" in resp.content
    assert b"docs.google.com/document/d/z" in resp.content


@pytest.mark.django_db
def test_board_sorts_by_param(authed, workspace):
    ContentIntake.objects.create(workspace=workspace, external_id="A", pillar_theme="Zeta",
        sensitivity="public_safe", status="idea")
    ContentIntake.objects.create(workspace=workspace, external_id="B", pillar_theme="Alpha",
        sensitivity="public_safe", status="idea")
    url = reverse("console:intake-board") + "?sort=pillar"
    resp = authed.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert body.index("Alpha") < body.index("Zeta")


@pytest.mark.django_db
def test_board_partial_returns_table_only(authed, workspace):
    ContentIntake.objects.create(workspace=workspace, external_id="A", pillar_theme="Energy",
        sensitivity="public_safe", status="idea")
    url = reverse("console:intake-board") + "?partial=1"
    resp = authed.get(url)
    assert resp.status_code == 200
    # Partial must NOT include the full page chrome (no <h1>Content Intake Board</h1>)
    assert b"intake-table" in resp.content
    assert b"Content Intake Board" not in resp.content


@pytest.mark.django_db
def test_sort_header_preserves_filters(authed, workspace):
    """Column-header sort links must carry the active status/pillar filters so a
    sort click does not silently reset them."""
    ContentIntake.objects.create(workspace=workspace, external_id="A", pillar_theme="Energy",
        sensitivity="public_safe", status="idea")
    url = reverse("console:intake-board") + "?status=idea&pillar=Energy"
    resp = authed.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # The pillar-sort header must round-trip both active filters.
    assert "?sort=pillar&status=idea&pillar=Energy" in body


@pytest.mark.django_db
def test_draft_now_panel_hx_success_rerenders_panel(authed, workspace):
    """Panel HX success re-renders _panel.html (preserving #intake-panel), not a
    card fragment, so subsequent row clicks still have a swap target."""
    from unittest.mock import patch

    item = ContentIntake.objects.create(workspace=workspace, external_id="P-1",
        pillar_theme="Energy", angle="Solar", sensitivity="public_safe", status="accepted")
    url = reverse("console:intake-draft-now-panel", args=[item.pk])

    def _fake_draft(obj):
        obj.status = ContentIntake.Status.DRAFTING
        obj.save(update_fields=["status"])
        return True

    with patch("apps.content_intake.views.request_herald_draft", side_effect=_fake_draft):
        resp = authed.post(url, HTTP_HX_REQUEST="true")

    assert resp.status_code == 200
    # The panel id is preserved (so row clicks keep their #intake-panel target)...
    assert b'id="intake-panel"' in resp.content
    # ...and no stray card fragment id is emitted.
    assert f"intake-card-{item.pk}".encode() not in resp.content


@pytest.mark.django_db
def test_draft_now_panel_hx_failure_retargets_panel(authed, workspace):
    """Panel HX failure surfaces the error banner and retargets #intake-panel (not
    a nonexistent #intake-card-{pk}), so the banner is not silently dropped."""
    from unittest.mock import patch

    item = ContentIntake.objects.create(workspace=workspace, external_id="P-2",
        pillar_theme="Energy", angle="Solar", sensitivity="public_safe", status="accepted")
    url = reverse("console:intake-draft-now-panel", args=[item.pk])

    with patch("apps.content_intake.views.request_herald_draft", return_value=False):
        resp = authed.post(url, HTTP_HX_REQUEST="true")

    assert resp.status_code == 200
    assert b"HERALD couldn't draft" in resp.content
    assert resp["HX-Retarget"] == "#intake-panel"
    assert resp["HX-Reswap"] == "afterbegin"


@pytest.mark.django_db
def test_sync_now_triggers_sync_and_returns_table(authed, workspace):
    from unittest.mock import patch
    url = reverse("console:intake-sync-now")
    with patch("apps.content_intake.views.sync_sheet_to_intake", return_value={"created": 0}) as m:
        resp = authed.post(url)
    assert resp.status_code == 200
    assert b"intake-table" in resp.content
    m.assert_called_once()
