"""Delete + edit orchestration for already-published platform posts.

LinkedIn (and several other networks) expose a delete endpoint but no edit
endpoint, so "edit a published post" is implemented as delete-then-recreate.
These operations live in ``apps.publisher.operations`` so the composer view and
any future API can reuse them.

Pinned behaviour:
- ``delete_published_post(pp)`` resolves credentials via the existing
  ``_resolve_publish_credentials``, calls ``provider.delete_post(token, urn)``,
  and marks the PlatformPost as no longer live (status back to draft, cleared
  ``platform_post_id``/``published_at``).
- ``edit_published_post(pp, new_caption)`` = delete old + re-publish new; the
  PlatformPost's ``platform_post_id`` is replaced with the new one and the
  caption override is updated.

All provider/network calls are mocked — no real API.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from providers.types import PublishResult


@pytest.fixture
def published_linkedin_pp(db):
    from apps.composer.models import PlatformPost, Post
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="Ops Org")
    ws = Workspace.objects.create(name="Ops WS", organization=org)
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="linkedin",
        account_platform_id="li-acct-1",
        account_name="LI Acct",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        oauth_access_token="li-token",
    )
    post = Post.objects.create(workspace=ws, author=None, caption="original caption", title="t")
    pp = PlatformPost.objects.create(
        post=post,
        social_account=account,
        status=PlatformPost.Status.PUBLISHED,
        platform_post_id="urn:li:share:111",
        published_at=timezone.now() - timedelta(hours=1),
    )
    return pp


class TestDeletePublishedPost:
    def test_calls_provider_delete_and_marks_removed(self, published_linkedin_pp, monkeypatch):
        from apps.composer.models import PlatformPost
        from apps.publisher import operations

        fake_provider = MagicMock()
        fake_provider.delete_post.return_value = True

        monkeypatch.setattr(operations, "get_provider", lambda platform, creds: fake_provider)

        result = operations.delete_published_post(published_linkedin_pp)

        assert result is True
        # Provider was asked to delete the right URN with the account's token.
        fake_provider.delete_post.assert_called_once()
        args, kwargs = fake_provider.delete_post.call_args
        call_args = list(args) + list(kwargs.values())
        assert "li-token" in call_args
        assert "urn:li:share:111" in call_args

        published_linkedin_pp.refresh_from_db()
        # No longer published / live on the platform.
        assert published_linkedin_pp.status != PlatformPost.Status.PUBLISHED
        assert published_linkedin_pp.platform_post_id == ""
        assert published_linkedin_pp.published_at is None

    def test_propagates_provider_failure(self, published_linkedin_pp, monkeypatch):
        from apps.composer.models import PlatformPost
        from apps.publisher import operations
        from providers.exceptions import PublishError

        fake_provider = MagicMock()
        fake_provider.delete_post.side_effect = PublishError("boom", platform="LinkedIn")
        monkeypatch.setattr(operations, "get_provider", lambda platform, creds: fake_provider)

        with pytest.raises(PublishError):
            operations.delete_published_post(published_linkedin_pp)

        published_linkedin_pp.refresh_from_db()
        # Failed delete leaves the live post untouched (still published).
        assert published_linkedin_pp.status == PlatformPost.Status.PUBLISHED
        assert published_linkedin_pp.platform_post_id == "urn:li:share:111"


class TestEditPublishedPost:
    def test_deletes_old_then_recreates_with_new_caption(self, published_linkedin_pp, monkeypatch):
        from apps.composer.models import PlatformPost
        from apps.publisher import operations

        fake_provider = MagicMock()
        fake_provider.delete_post.return_value = True
        fake_provider.publish_post.return_value = PublishResult(
            platform_post_id="urn:li:share:222",
            url="https://www.linkedin.com/feed/update/urn:li:share:222/",
        )
        monkeypatch.setattr(operations, "get_provider", lambda platform, creds: fake_provider)

        result = operations.edit_published_post(published_linkedin_pp, "edited caption")

        # Old post deleted, new post created.
        fake_provider.delete_post.assert_called_once()
        fake_provider.publish_post.assert_called_once()

        published_linkedin_pp.refresh_from_db()
        assert published_linkedin_pp.status == PlatformPost.Status.PUBLISHED
        assert published_linkedin_pp.platform_post_id == "urn:li:share:222"
        # New caption persisted as the platform override.
        assert published_linkedin_pp.effective_caption == "edited caption"
        # The re-publish carried the new caption text.
        _, pub_kwargs = fake_provider.publish_post.call_args
        content = pub_kwargs.get("content") or fake_provider.publish_post.call_args.args[-1]
        assert content.text == "edited caption"
        assert result.platform_post_id == "urn:li:share:222"
