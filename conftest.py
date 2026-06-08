import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership
from apps.organizations.models import Organization


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="test@example.com", password="testpass123", name="Test User", tos_accepted_at=timezone.now()
    )


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Test Organization")


@pytest.fixture
def org_owner(db, user, organization):
    OrgMembership.objects.create(user=user, organization=organization, org_role=OrgMembership.OrgRole.OWNER)
    return user


@pytest.fixture
def due_platform_post_factory(db, organization):
    """Build a due PlatformPost (status=scheduled, scheduled_at in the past).

    Creates the Workspace + SocialAccount + Post + PlatformPost chain so the
    publish engine's poll loop picks it up immediately. Accepts ``gate_id``,
    ``content_hash`` and ``platform`` to exercise the gate hook.
    """
    from datetime import timedelta

    from apps.composer.models import PlatformPost, Post
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    def _make(*, gate_id=None, content_hash="", platform="mock", caption="real text"):
        workspace = Workspace.objects.create(name="GateHook WS", organization=organization)
        account = SocialAccount.objects.create(
            workspace=workspace,
            platform=platform,
            account_platform_id=f"acct-{platform}",
            account_name=f"{platform} acct",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        post = Post.objects.create(workspace=workspace, author=None, caption=caption, title="t")
        return PlatformPost.objects.create(
            post=post,
            social_account=account,
            status=PlatformPost.Status.SCHEDULED,
            scheduled_at=timezone.now() - timedelta(minutes=5),
            gate_id=gate_id,
            content_hash=content_hash,
        )

    return _make
