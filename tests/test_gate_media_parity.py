"""FIX B regression: content-hash parity (text-only on both sides).

agent-service gates on canonical_content_hash(content) — TEXT ONLY. The fork
must hash the same way at the store site, so a post carrying MEDIA still
matches the approver's hash and publishes. If the fork bound media_refs into
the gated hash, any post with an attachment would diverge and be GATE BLOCKed
forever.

This test attaches a real media asset to a gated post, stubs verify_gate to
return the TEXT-ONLY hash with verdict "pass", and asserts it publishes via the
mock provider despite media being present.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.composer.models import PlatformPost, PostMedia, Post
from apps.media_library.models import MediaAsset
from apps.publisher.engine import Publisher
from apps.publisher.gate_hash import canonical_content_hash
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


@pytest.mark.django_db
def test_gated_post_with_media_publishes_text_only_hash(organization, settings):
    settings.ENABLE_MOCK_PROVIDER = True

    caption = "approved caption"
    ws = Workspace.objects.create(name="MediaParity WS", organization=organization)
    acct = SocialAccount.objects.create(
        workspace=ws,
        platform="mock",
        account_platform_id="acct-mock",
        account_name="mock acct",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    post = Post.objects.create(workspace=ws, author=None, caption=caption, title="t")

    # Attach a real media asset (file exists under MEDIA_ROOT=test_media) so
    # the dispatch path actually downloads media — proving media presence does
    # not change the gated hash.
    asset = MediaAsset.objects.create(
        organization=organization,
        workspace=ws,
        uploaded_by=None,
        file="media_library/2026/06/shared.png",
        filename="shared.png",
        media_type=MediaAsset.MediaType.IMAGE,
        mime_type="image/png",
        file_size=11,
        source="upload",
    )
    PostMedia.objects.create(post=post, media_asset=asset, position=0)

    # content_hash is TEXT ONLY (FIX B) — no media_refs.
    text_only_hash = canonical_content_hash(caption)
    assert post.media_attachments.count() == 1  # media really is present

    pp = PlatformPost.objects.create(
        post=post,
        social_account=acct,
        status=PlatformPost.Status.SCHEDULED,
        scheduled_at=timezone.now() - timedelta(minutes=5),
        gate_id="33333333-3333-3333-3333-333333333333",
        content_hash=text_only_hash,
    )

    # Approver returns the TEXT-ONLY hash (its only knowledge of the content).
    with patch(
        "apps.publisher.engine.verify_gate",
        return_value={"verdict": "pass", "content_hash": text_only_hash},
    ):
        Publisher().poll_and_publish()

    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.PUBLISHED
    assert pp.platform_post_id.startswith("mock_")
