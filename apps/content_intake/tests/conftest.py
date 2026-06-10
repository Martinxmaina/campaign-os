import pytest
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


@pytest.fixture
def workspace(db):
    org = Organization.objects.create(name="AfCEN Test")
    return Workspace.objects.create(organization=org, name="WAIIS")


@pytest.fixture
def platform_post_factory(db):
    """Create a PlatformPost (and its Post + SocialAccount chain) for a given workspace.

    Used in dispatch-linkage tests to verify that intake.post references the
    correct Post the engine would traverse when it calls check_intake_gate.
    """
    from django.utils import timezone
    from datetime import timedelta

    from apps.composer.models import PlatformPost, Post
    from apps.social_accounts.models import SocialAccount

    def _make(*, workspace, platform="mock", caption="test caption"):
        account = SocialAccount.objects.create(
            workspace=workspace,
            platform=platform,
            account_platform_id=f"acct-{platform}",
            account_name=f"{platform} acct",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        post = Post.objects.create(
            workspace=workspace,
            author=None,
            caption=caption,
            title="test",
        )
        pp = PlatformPost.objects.create(
            post=post,
            social_account=account,
            status=PlatformPost.Status.SCHEDULED,
            scheduled_at=timezone.now() - timedelta(minutes=5),
        )
        return pp

    return _make
