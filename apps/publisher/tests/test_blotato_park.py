# apps/publisher/tests/test_blotato_park.py
from unittest.mock import patch

import pytest


@pytest.fixture
def blotato_pp(db):
    from datetime import timedelta
    from django.utils import timezone
    from apps.composer.models import PlatformPost, Post
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    acct = SocialAccount.objects.create(
        workspace=ws, platform="blotato_instagram", account_platform_id="98432",
        account_name="AfCEN", connection_status=SocialAccount.ConnectionStatus.CONNECTED)
    post = Post.objects.create(workspace=ws, caption="hello")
    return PlatformPost.objects.create(
        post=post, social_account=acct, status=PlatformPost.Status.SCHEDULED,
        scheduled_at=timezone.now() - timedelta(minutes=1))


@pytest.mark.django_db
def test_still_publishing_parks_at_publishing_without_retry(blotato_pp):
    from apps.composer.models import PlatformPost
    from apps.publisher.engine import PublishEngine
    from providers.exceptions import BlotatoStillPublishing

    with patch.object(PublishEngine, "_dispatch_to_provider",
                      side_effect=BlotatoStillPublishing("sub_99")), \
         patch.object(PublishEngine, "_schedule_retry") as retry:
        PublishEngine()._publish_platform_post(blotato_pp)

    blotato_pp.refresh_from_db()
    assert blotato_pp.status == PlatformPost.Status.PUBLISHING
    assert blotato_pp.platform_post_id == "sub_99"
    retry.assert_not_called()  # parked for reconcile, NOT retried
