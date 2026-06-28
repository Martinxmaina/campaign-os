"""Hybrid inline-image upload for the Ghost article editor.

- Always stores the asset in the media library.
- When a Ghost channel is connected, re-hosts to Ghost immediately so the
  article <img src> is permanent (not an expiring presigned URL).
- Falls back to the media URL otherwise (publish-time re-host is the safety net).
- Does NOT attach the image as a post carousel attachment (it lives inline).
"""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.composer.models import PostMedia
from apps.media_library.models import MediaAsset
from apps.members.models import WorkspaceMembership
from apps.social_accounts.models import SocialAccount

pytestmark = pytest.mark.django_db


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(buf, format="PNG")
    return buf.getvalue()


def _upload(client, workspace):
    img = SimpleUploadedFile("inline.png", _png(), content_type="image/png")
    return client.post(
        reverse("composer:upload_inline_image", kwargs={"workspace_id": workspace.id}), {"file": img}
    )


def test_no_ghost_falls_back_to_media_url(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)

    resp = _upload(client, workspace)
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "media"
    assert data["url"]
    assert resp["X-Uploaded-Asset-Url"] == data["url"]
    # Asset stored, but NOT attached as a post carousel attachment.
    assert MediaAsset.objects.filter(workspace=workspace).count() == 1
    assert PostMedia.objects.count() == 0


def test_ghost_connected_rehosts_immediately(client, workspace, make_user_in_workspace, monkeypatch):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    SocialAccount.objects.create(
        workspace=workspace, platform="ghost", account_platform_id="g-1", account_name="Nexus Brief"
    )

    ghost_url = "https://blog.example.com/content/images/2026/06/inline.png"

    class _FakeGhost:
        def upload_image_bytes(self, content, filename="image.jpg", content_type="image/jpeg"):
            return ghost_url

    import providers

    monkeypatch.setattr(providers, "get_provider", lambda *a, **k: _FakeGhost())

    resp = _upload(client, workspace)
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "ghost"
    assert data["url"] == ghost_url
    assert resp["X-Uploaded-Asset-Url"] == ghost_url
    # Still stored in the library as a backup.
    assert MediaAsset.objects.filter(workspace=workspace).count() == 1
