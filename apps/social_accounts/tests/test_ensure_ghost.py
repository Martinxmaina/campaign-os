"""Tests for Ghost analytics permanence + auto-connect from env.

Covers:
- The data migration seeds an *enabled* ghost AnalyticsPlatformConfig row.
- ``ensure_ghost_connected`` management command:
  - env key set + no ghost SocialAccount  -> creates a connected ghost account
    (network mocked via get_provider(...).get_profile).
  - already-connected ghost              -> no duplicate.
  - no env key                           -> no-op (no account, no crash).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.social_accounts.models import AnalyticsPlatformConfig, SocialAccount

GHOST_ENV = {
    "ghost": {
        "admin_api_key": "abc:123",
        "base_url": "https://the-nexus-brief.ghost.io",
        "newsletter_slug": "",
    }
}


@pytest.fixture
def organization(db):
    from apps.organizations.models import Organization

    return Organization.objects.create(name="WAIIS")


@pytest.fixture
def workspace(db, organization):
    from apps.workspaces.models import Workspace

    return Workspace.objects.create(name="AfCEN", organization=organization)


def _profile():
    return SimpleNamespace(
        platform_id="https://the-nexus-brief.ghost.io",
        name="The Nexus Brief",
        handle=None,
    )


@pytest.mark.django_db
class TestGhostAnalyticsSeed:
    def test_ghost_analytics_config_enabled_by_default(self):
        """The data migration leaves a ghost row that is analytics-enabled."""
        row = AnalyticsPlatformConfig.objects.filter(platform="ghost").first()
        assert row is not None, "data migration must seed a ghost AnalyticsPlatformConfig row"
        assert row.is_enabled is True
        assert "ghost" in AnalyticsPlatformConfig.enabled_platforms()


@pytest.mark.django_db
class TestEnsureGhostConnected:
    def test_creates_connected_account_when_env_key_set(self, workspace, settings):
        from apps.workspaces.models import Workspace

        settings.PLATFORM_CREDENTIALS_FROM_ENV = {**settings.PLATFORM_CREDENTIALS_FROM_ENV, **GHOST_ENV}
        provider = MagicMock()
        provider.get_profile.return_value = _profile()
        oldest_ws = Workspace.objects.order_by("created_at").first()

        with patch("apps.social_accounts.management.commands.ensure_ghost_connected.get_provider", return_value=provider) as mock_get:
            call_command("ensure_ghost_connected")

        mock_get.assert_called_once()
        accounts = SocialAccount.objects.filter(platform="ghost")
        assert accounts.count() == 1
        acct = accounts.first()
        # Attaches to the org's oldest workspace (like connect_ghost).
        assert acct.workspace_id == oldest_ws.id
        assert acct.account_name == "The Nexus Brief"
        assert acct.connection_status == SocialAccount.ConnectionStatus.CONNECTED

    def test_idempotent_no_duplicate_when_already_connected(self, workspace, settings):
        settings.PLATFORM_CREDENTIALS_FROM_ENV = {**settings.PLATFORM_CREDENTIALS_FROM_ENV, **GHOST_ENV}
        provider = MagicMock()
        provider.get_profile.return_value = _profile()

        with patch("apps.social_accounts.management.commands.ensure_ghost_connected.get_provider", return_value=provider):
            call_command("ensure_ghost_connected")
            call_command("ensure_ghost_connected")

        assert SocialAccount.objects.filter(platform="ghost").count() == 1

    def test_noop_when_no_env_key(self, workspace, settings):
        env = dict(settings.PLATFORM_CREDENTIALS_FROM_ENV)
        env.pop("ghost", None)
        settings.PLATFORM_CREDENTIALS_FROM_ENV = env

        with patch("apps.social_accounts.management.commands.ensure_ghost_connected.get_provider") as mock_get:
            call_command("ensure_ghost_connected")

        mock_get.assert_not_called()
        assert SocialAccount.objects.filter(platform="ghost").count() == 0

    def test_noop_when_validation_fails(self, workspace, settings):
        """Ghost validation raising must not crash boot and must not create a row."""
        settings.PLATFORM_CREDENTIALS_FROM_ENV = {**settings.PLATFORM_CREDENTIALS_FROM_ENV, **GHOST_ENV}
        provider = MagicMock()
        provider.get_profile.side_effect = RuntimeError("Ghost down")

        with patch("apps.social_accounts.management.commands.ensure_ghost_connected.get_provider", return_value=provider):
            call_command("ensure_ghost_connected")  # must not raise

        assert SocialAccount.objects.filter(platform="ghost").count() == 0
