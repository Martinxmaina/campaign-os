"""Fixtures shared across approvals tests."""
import pytest
from apps.social_accounts.models import SocialAccount


@pytest.fixture
def social_account(db, workspace):
    """Return a factory: social_account(platform) -> SocialAccount."""
    created = []

    def _make(platform="linkedin", account_name=None, account_handle=""):
        sa = SocialAccount.objects.create(
            workspace=workspace,
            platform=platform,
            account_platform_id=f"acct-{platform}-{len(created)}",
            account_name=account_name or f"{platform} account",
            account_handle=account_handle,
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        created.append(sa)
        return sa

    return _make
