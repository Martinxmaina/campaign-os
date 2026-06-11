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
