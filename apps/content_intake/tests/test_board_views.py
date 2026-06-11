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
    # Partial must NOT include the full page chrome (no <h1 Content Intake)
    assert b"intake-table" in resp.content
