"""FIX D regression: the first-comment task re-verifies the parent post's
approval gate before calling provider.publish_comment.

- A parent with gate_id=None (e.g. cleared by an edit) → comment is skipped,
  provider.publish_comment is never called.
- A parent whose gate verdict is not pass/approved → comment is skipped.
- A parent with a present gate_id + pass verdict → comment is posted.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.publisher.engine import _post_first_comment_task
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


def _published_pp_with_comment(organization, *, gate_id, platform="mock"):
    ws = Workspace.objects.create(name="FirstComment WS", organization=organization)
    acct = SocialAccount.objects.create(
        workspace=ws,
        platform=platform,
        account_platform_id=f"acct-{platform}",
        account_name=f"{platform} acct",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    post = Post.objects.create(
        workspace=ws, author=None, caption="body", title="t", first_comment="hello comment"
    )
    return PlatformPost.objects.create(
        post=post,
        social_account=acct,
        status=PlatformPost.Status.PUBLISHED,
        platform_post_id="mock_123",
        published_at=timezone.now() - timedelta(seconds=1),
        gate_id=gate_id,
        content_hash="irrelevant",
    )


@pytest.mark.django_db
def test_first_comment_skipped_when_gate_cleared(organization):
    pp = _published_pp_with_comment(organization, gate_id=None)
    with patch("apps.publisher.engine.get_provider") as gp:
        _post_first_comment_task.now(str(pp.id))
        gp.assert_not_called()


@pytest.mark.django_db
def test_first_comment_skipped_when_gate_not_passing(organization):
    pp = _published_pp_with_comment(
        organization, gate_id="55555555-5555-5555-5555-555555555555"
    )
    with patch(
        "apps.publisher.engine.verify_gate",
        return_value={"verdict": "rejected", "content_hash": "x"},
    ), patch("apps.publisher.engine.get_provider") as gp:
        _post_first_comment_task.now(str(pp.id))
        gp.assert_not_called()


@pytest.mark.django_db
def test_first_comment_posted_when_gate_passes(organization):
    pp = _published_pp_with_comment(
        organization, gate_id="66666666-6666-6666-6666-666666666666"
    )
    provider = MagicMock()
    with patch(
        "apps.publisher.engine.verify_gate",
        return_value={"verdict": "pass", "content_hash": "x"},
    ), patch("apps.publisher.engine.get_provider", return_value=provider):
        _post_first_comment_task.now(str(pp.id))
    provider.publish_comment.assert_called_once()
    _, kwargs = provider.publish_comment.call_args
    assert kwargs["text"] == "hello comment"
