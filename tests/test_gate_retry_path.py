"""FIX A regression: the authoritative gate lives at the provider dispatch
chokepoint, so EVERY publish path is gated — including the retry path
(_process_retries → _publish_platform_post → _dispatch_to_provider), which
never calls the early _publish_post_group fail-fast filter.

A PlatformPost with gate_id=None (or a mismatched content_hash) must NOT reach
the provider via the retry path: get_provider is never called, the post is not
PUBLISHED, and no further retry is scheduled for a gate block.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.publisher.engine import Publisher
from apps.publisher.gate_hash import canonical_content_hash
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


def _make_retry_post(organization, *, gate_id, content_hash, platform="mock"):
    """Build a PlatformPost already in the retry queue (retry_count>0,
    next_retry_at in the past) so _process_retries picks it up directly,
    bypassing _publish_post_group / _gate_ok entirely."""
    ws = Workspace.objects.create(name="RetryGate WS", organization=organization)
    acct = SocialAccount.objects.create(
        workspace=ws,
        platform=platform,
        account_platform_id=f"acct-{platform}",
        account_name=f"{platform} acct",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    post = Post.objects.create(workspace=ws, author=None, caption="real text", title="t")
    return PlatformPost.objects.create(
        post=post,
        social_account=acct,
        status=PlatformPost.Status.SCHEDULED,
        scheduled_at=timezone.now() - timedelta(minutes=10),
        retry_count=1,
        next_retry_at=timezone.now() - timedelta(minutes=1),
        gate_id=gate_id,
        content_hash=content_hash,
    )


@pytest.mark.django_db
def test_retry_path_blocks_missing_gate_id(organization):
    pp = _make_retry_post(organization, gate_id=None, content_hash="")
    with patch("apps.publisher.engine.get_provider") as gp:
        Publisher()._process_retries()
        gp.assert_not_called()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.FAILED
    assert pp.status != PlatformPost.Status.PUBLISHED
    assert "GATE BLOCK" in pp.publish_error
    # Gate block is terminal: retry_count must not have advanced and the post
    # must not be re-queued as SCHEDULED for another attempt.
    assert pp.retry_count == 1


@pytest.mark.django_db
def test_retry_path_blocks_hash_mismatch(organization):
    pp = _make_retry_post(
        organization,
        gate_id="11111111-1111-1111-1111-111111111111",
        content_hash=canonical_content_hash("real text"),
    )
    with patch(
        "apps.publisher.engine.verify_gate",
        return_value={"verdict": "pass", "content_hash": "DIFFERENT"},
    ), patch("apps.publisher.engine.get_provider") as gp:
        Publisher()._process_retries()
        gp.assert_not_called()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.FAILED
    assert pp.status != PlatformPost.Status.PUBLISHED


@pytest.mark.django_db
def test_retry_path_publishes_when_gate_passes(organization, settings):
    settings.ENABLE_MOCK_PROVIDER = True
    h = canonical_content_hash("real text")
    pp = _make_retry_post(
        organization,
        gate_id="22222222-2222-2222-2222-222222222222",
        content_hash=h,
        platform="mock",
    )
    with patch(
        "apps.publisher.engine.verify_gate",
        return_value={"verdict": "pass", "content_hash": h},
    ):
        Publisher()._process_retries()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.PUBLISHED
    assert pp.platform_post_id.startswith("mock_")
