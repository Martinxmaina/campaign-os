"""Per-account logo upload — lets users identify accounts by their logo."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.members.models import WorkspaceMembership
from apps.social_accounts.models import SocialAccount

pytestmark = pytest.mark.django_db


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), "red").save(buf, format="PNG")
    return buf.getvalue()


def _account(workspace):
    return SocialAccount.objects.create(
        workspace=workspace,
        platform="blotato_linkedin",
        account_platform_id="logo-test-1",
        account_name="Test LinkedIn",
    )


def test_upload_logo_sets_and_displays(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.ADMIN)
    client.force_login(user)
    acct = _account(workspace)
    assert acct.logo_display_url == ""  # no logo, no avatar yet

    url = reverse("social_accounts:set_logo", kwargs={"workspace_id": workspace.id, "account_id": acct.id})
    img = SimpleUploadedFile("brand.png", _png(), content_type="image/png")
    resp = client.post(url, {"logo": img})

    assert resp.status_code in (200, 302)
    acct.refresh_from_db()
    assert bool(acct.logo)
    assert acct.logo_display_url  # now resolves to the uploaded file URL


def test_non_image_rejected(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.ADMIN)
    client.force_login(user)
    acct = _account(workspace)

    url = reverse("social_accounts:set_logo", kwargs={"workspace_id": workspace.id, "account_id": acct.id})
    bad = SimpleUploadedFile("notimage.txt", b"hello, not an image", content_type="text/plain")
    resp = client.post(url, {"logo": bad})

    assert resp.status_code in (200, 302)
    acct.refresh_from_db()
    assert not bool(acct.logo)
