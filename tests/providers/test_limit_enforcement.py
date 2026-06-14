"""Publish-time caption-limit enforcement + no-silent-truncation.

Two layers are pinned here:

1. ``PublishEngine._dispatch_to_provider`` must REJECT (raise ``PublishError``)
   a post whose effective caption is longer than the provider's
   ``max_caption_length`` *before* hitting the network — it must NOT silently
   truncate. The PublishLog records the failure.

2. The Threads + YouTube providers no longer carry the ``[: max_caption_length]``
   silent slice on the caption/description: an over-limit caption reaches the
   provider intact (the engine guard is the single rejection point). We assert
   the provider sends the full text, not a truncated copy.

All network is mocked — no real API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from providers.exceptions import PublishError
from providers.types import AuthType, MediaType, PostType, PublishContent, PublishResult


# ---------------------------------------------------------------------------
# Engine-level guard
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Minimal provider used to assert the engine guard fires before dispatch."""

    auth_type = AuthType.OAUTH2
    max_caption_length = 500
    supported_post_types = [PostType.TEXT, PostType.IMAGE, PostType.VIDEO]

    def __init__(self):
        self.publish_calls = []

    def publish_post(self, access_token, content):  # pragma: no cover - must NOT run
        self.publish_calls.append(content)
        return PublishResult(platform_post_id="should-not-happen")


@pytest.fixture
def org_ws(db):
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="LimitGuard Org")
    ws = Workspace.objects.create(name="LimitGuard WS", organization=org)
    return org, ws


@pytest.fixture
def threads_account(db, org_ws):
    from apps.social_accounts.models import SocialAccount

    _org, ws = org_ws
    return SocialAccount.objects.create(
        workspace=ws,
        platform="threads",
        account_platform_id="th-guard",
        account_name="Guard Threads",
        connection_status="connected",
        oauth_access_token="tok",
    )


@pytest.fixture
def over_limit_pp(db, org_ws, threads_account):
    """A gate-bypassed PlatformPost whose caption exceeds the Threads limit."""
    from apps.composer.models import PlatformPost, Post

    _org, ws = org_ws
    post = Post.objects.create(workspace=ws, caption="x" * 501)
    return PlatformPost.objects.create(
        post=post,
        social_account=threads_account,
        status=PlatformPost.Status.PUBLISHING,
        gate_bypassed=True,
    )


@pytest.mark.django_db
class TestEngineCaptionGuard:
    def test_over_limit_raises_publish_error_before_dispatch(self, over_limit_pp):
        from apps.publisher.engine import PublishEngine

        fake = _FakeProvider()
        engine = PublishEngine()
        with patch("apps.publisher.engine.get_provider", return_value=fake):
            with pytest.raises(PublishError) as exc:
                engine._dispatch_to_provider(over_limit_pp)

        # The provider was never called — guard fired first.
        assert fake.publish_calls == []
        msg = str(exc.value)
        assert "threads" in msg
        assert "501" in msg

    def test_publish_log_records_over_limit(self, over_limit_pp):
        """Going through the full single-post path records a PublishLog with
        the over-limit error and marks the post failed (after retries)."""
        from apps.publisher.engine import PublishEngine
        from apps.publisher.models import PublishLog

        fake = _FakeProvider()
        engine = PublishEngine()
        with patch("apps.publisher.engine.get_provider", return_value=fake):
            engine._publish_platform_post(over_limit_pp)

        logs = list(PublishLog.objects.filter(platform_post=over_limit_pp))
        assert logs, "expected a PublishLog row for the over-limit failure"
        assert any("501" in (log.error_message or "") for log in logs)
        assert fake.publish_calls == []

    def test_under_limit_dispatches(self, db, org_ws, threads_account):
        from apps.composer.models import PlatformPost, Post
        from apps.publisher.engine import PublishEngine

        _org, ws = org_ws
        post = Post.objects.create(workspace=ws, caption="x" * 500)
        pp = PlatformPost.objects.create(
            post=post,
            social_account=threads_account,
            status=PlatformPost.Status.PUBLISHING,
            gate_bypassed=True,
        )
        fake = _FakeProvider()
        engine = PublishEngine()
        with patch("apps.publisher.engine.get_provider", return_value=fake):
            result = engine._dispatch_to_provider(pp)

        assert result["success"] is True
        assert len(fake.publish_calls) == 1
        # Full caption reached the provider (no truncation).
        assert fake.publish_calls[0].text == "x" * 500


# ---------------------------------------------------------------------------
# Provider no-silent-truncation
# ---------------------------------------------------------------------------


def _resp(payload: dict, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.json = MagicMock(return_value=payload)
    resp.headers = headers or {}
    return resp


class TestThreadsNoTruncation:
    @patch("providers.threads.ThreadsProvider._request")
    def test_single_sends_full_text(self, mock_request):
        from providers.threads import ThreadsProvider

        long_text = "x" * 600  # > Threads' 500 limit
        # _get_user_id, create container, publish — return ids in sequence.
        mock_request.side_effect = [
            _resp({"id": "user-1"}),
            _resp({"id": "container-1"}),
            _resp({"id": "thread-1"}),
        ]
        provider = ThreadsProvider()
        content = PublishContent(text=long_text, post_type=PostType.TEXT)
        provider.publish_post("tok", content)

        # Find the create-container call and assert the text is NOT truncated.
        container_call = mock_request.call_args_list[1]
        sent_text = container_call.kwargs.get("data", {}).get("text") or container_call.kwargs.get(
            "json", {}
        ).get("text")
        assert sent_text == long_text


class TestYouTubeNoTruncation:
    @patch("providers.youtube.YouTubeProvider._request")
    def test_video_description_not_truncated(self, mock_request, tmp_path):
        from providers.youtube import YouTubeProvider

        long_desc = "x" * 6000  # > YouTube's 5000 limit
        # init resumable upload returns a Location header; the PUT upload
        # returns the created video id.
        mock_request.side_effect = [
            _resp({}, headers={"Location": "https://upload.example/abc"}),
            _resp({"id": "vid-1"}, headers={}),
        ]
        video_file = tmp_path / "clip.mp4"
        video_file.write_bytes(b"\x00\x00\x00\x18ftypmp42")

        provider = YouTubeProvider()
        content = PublishContent(
            title="My Video",
            description=long_desc,
            media_files=[str(video_file)],
            post_type=PostType.VIDEO,
        )
        result = provider.publish_post("tok", content)
        assert result.platform_post_id == "vid-1"

        # The metadata (snippet) call must carry the FULL description.
        init_call = mock_request.call_args_list[0]
        sent_desc = init_call.kwargs["json"]["snippet"]["description"]
        assert sent_desc == long_desc
