"""401-on-publish hardening: refresh the OAuth token and retry ONCE.

A connected account's access token can expire between the pre-publish
expiry check and the actual provider call (clock skew, server-side
revocation, a token that died early). When the provider answers the
publish with a 401/auth error and the account carries a refresh token,
the engine should refresh + persist the new tokens and retry the publish
exactly once — NOT fall into the exponential backoff loop (which would
keep replaying the same dead token for up to 30 minutes per attempt).

If there is no refresh token, or the single retry still 401s, the account
is marked needs-reconnect (connection_status=ERROR) and the failure is
logged to PublishLog as usual.

All provider/network calls are mocked — no real API.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from providers.exceptions import APIError
from providers.types import AuthType, OAuthTokens, PublishResult


@pytest.fixture
def scheduled_oauth_pp(db):
    """A SCHEDULED PlatformPost on an OAUTH2 account with a refresh token."""
    from apps.composer.models import PlatformPost, Post
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="Refresh Org")
    ws = Workspace.objects.create(name="Refresh WS", organization=org)
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="linkedin",
        account_platform_id="li-acct-401",
        account_name="LI 401 Acct",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        oauth_access_token="dead-token",
        oauth_refresh_token="refresh-me",
        # Far in the future so the pre-publish expiry refresh does NOT fire —
        # the only refresh under test is the 401-triggered one.
        token_expires_at=timezone.now() + timedelta(days=60),
    )
    post = Post.objects.create(workspace=ws, author=None, caption="hello world", title="t")
    pp = PlatformPost.objects.create(
        post=post,
        social_account=account,
        status=PlatformPost.Status.PUBLISHING,
        gate_bypassed=True,  # skip the approval gate for this unit test
    )
    return pp


def _make_provider(*, publish_side_effects):
    """Build a fake OAUTH2 provider with a refresh_token + scripted publish."""
    provider = MagicMock()
    provider.auth_type = AuthType.OAUTH2
    provider.max_caption_length = 3000
    provider.supported_post_types = []
    provider.publish_post.side_effect = publish_side_effects
    provider.refresh_token.return_value = OAuthTokens(
        access_token="fresh-token",
        refresh_token="fresh-refresh",
        expires_in=3600,
    )
    return provider


class TestPublish401RefreshRetry:
    def test_refreshes_and_retries_once_on_401_then_succeeds(self, scheduled_oauth_pp, monkeypatch):
        from apps.publisher import engine as engine_mod
        from apps.social_accounts.models import SocialAccount

        # First publish 401s; after refresh the retry succeeds.
        provider = _make_provider(
            publish_side_effects=[
                APIError("LinkedIn API error 401: token expired", status_code=401, platform="LinkedIn"),
                PublishResult(platform_post_id="urn:li:share:999", url="https://x/999"),
            ]
        )
        monkeypatch.setattr(engine_mod, "get_provider", lambda platform, creds: provider)
        monkeypatch.setattr(engine_mod, "_resolve_publish_credentials", lambda account: {})

        eng = engine_mod.PublishEngine()
        result = eng._dispatch_to_provider(scheduled_oauth_pp)

        assert result["success"] is True
        assert result["platform_post_id"] == "urn:li:share:999"

        # Refresh was called once with the stored refresh token.
        provider.refresh_token.assert_called_once_with("refresh-me")
        # Publish attempted exactly twice (initial 401 + one retry).
        assert provider.publish_post.call_count == 2

        # New tokens persisted; account stays CONNECTED.
        account = SocialAccount.objects.get(id=scheduled_oauth_pp.social_account_id)
        assert account.oauth_access_token == "fresh-token"
        assert account.oauth_refresh_token == "fresh-refresh"
        assert account.connection_status == SocialAccount.ConnectionStatus.CONNECTED

        # The retry used the freshly-minted token.
        retry_token = provider.publish_post.call_args_list[1].args[0]
        assert retry_token == "fresh-token"

    def test_no_refresh_token_marks_reconnect_and_propagates(self, scheduled_oauth_pp, monkeypatch):
        from apps.publisher import engine as engine_mod
        from apps.social_accounts.models import SocialAccount

        # Strip the refresh token: there is nothing to refresh with.
        account = scheduled_oauth_pp.social_account
        account.oauth_refresh_token = ""
        account.save(update_fields=["oauth_refresh_token"])

        provider = _make_provider(
            publish_side_effects=[
                APIError("LinkedIn API error 401", status_code=401, platform="LinkedIn"),
            ]
        )
        monkeypatch.setattr(engine_mod, "get_provider", lambda platform, creds: provider)
        monkeypatch.setattr(engine_mod, "_resolve_publish_credentials", lambda account: {})

        eng = engine_mod.PublishEngine()
        with pytest.raises(APIError):
            eng._dispatch_to_provider(scheduled_oauth_pp)

        # No refresh attempted, no retry.
        provider.refresh_token.assert_not_called()
        assert provider.publish_post.call_count == 1

        account = SocialAccount.objects.get(id=scheduled_oauth_pp.social_account_id)
        assert account.connection_status == SocialAccount.ConnectionStatus.ERROR
        assert account.needs_reconnect is True

    def test_retry_still_401_marks_reconnect_and_propagates(self, scheduled_oauth_pp, monkeypatch):
        from apps.publisher import engine as engine_mod
        from apps.social_accounts.models import SocialAccount

        # Both the initial publish AND the post-refresh retry 401.
        provider = _make_provider(
            publish_side_effects=[
                APIError("LinkedIn API error 401", status_code=401, platform="LinkedIn"),
                APIError("LinkedIn API error 401 again", status_code=401, platform="LinkedIn"),
            ]
        )
        monkeypatch.setattr(engine_mod, "get_provider", lambda platform, creds: provider)
        monkeypatch.setattr(engine_mod, "_resolve_publish_credentials", lambda account: {})

        eng = engine_mod.PublishEngine()
        with pytest.raises(APIError):
            eng._dispatch_to_provider(scheduled_oauth_pp)

        # Refreshed once, retried once, then gave up.
        provider.refresh_token.assert_called_once()
        assert provider.publish_post.call_count == 2

        account = SocialAccount.objects.get(id=scheduled_oauth_pp.social_account_id)
        assert account.connection_status == SocialAccount.ConnectionStatus.ERROR
        assert account.needs_reconnect is True

    def test_non_auth_error_is_not_retried_by_refresh_path(self, scheduled_oauth_pp, monkeypatch):
        from apps.publisher import engine as engine_mod
        from apps.social_accounts.models import SocialAccount

        # A 500 is NOT an auth failure — the refresh-retry path must ignore it
        # and let the normal backoff loop handle it. Account stays CONNECTED.
        provider = _make_provider(
            publish_side_effects=[
                APIError("LinkedIn API error 500", status_code=500, platform="LinkedIn"),
            ]
        )
        monkeypatch.setattr(engine_mod, "get_provider", lambda platform, creds: provider)
        monkeypatch.setattr(engine_mod, "_resolve_publish_credentials", lambda account: {})

        eng = engine_mod.PublishEngine()
        with pytest.raises(APIError):
            eng._dispatch_to_provider(scheduled_oauth_pp)

        provider.refresh_token.assert_not_called()
        assert provider.publish_post.call_count == 1

        account = SocialAccount.objects.get(id=scheduled_oauth_pp.social_account_id)
        assert account.connection_status == SocialAccount.ConnectionStatus.CONNECTED
