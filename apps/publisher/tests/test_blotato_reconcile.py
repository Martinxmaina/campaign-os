# apps/publisher/tests/test_blotato_reconcile.py
from unittest.mock import MagicMock, patch

import pytest


def _pp(db, status_field):
    from apps.composer.models import PlatformPost, Post
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    acct = SocialAccount.objects.create(
        workspace=ws, platform="blotato_instagram", account_platform_id="1", account_name="A")
    post = Post.objects.create(workspace=ws, caption="x")
    return PlatformPost.objects.create(
        post=post, social_account=acct, status=PlatformPost.Status.PUBLISHING,
        platform_post_id="sub_42")


@pytest.mark.django_db
def test_reconcile_finalizes_published(db):
    from apps.composer.models import PlatformPost
    from apps.publisher.tasks import reconcile_blotato_posts
    pp = _pp(db, "publishing")
    fake = MagicMock()
    fake.check_status.return_value = {"status": "published", "publicUrl": "https://ig/1"}
    with patch("apps.publisher.tasks.get_provider", return_value=fake), \
         patch("apps.publisher.tasks._resolve_publish_credentials", return_value={"api_key": "k"}):
        reconcile_blotato_posts()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.PUBLISHED
    assert pp.published_at is not None


@pytest.mark.django_db
def test_reconcile_finalizes_failed(db):
    from apps.composer.models import PlatformPost
    from apps.publisher.tasks import reconcile_blotato_posts
    pp = _pp(db, "publishing")
    fake = MagicMock()
    fake.check_status.return_value = {"status": "failed", "errorMessage": "rejected"}
    with patch("apps.publisher.tasks.get_provider", return_value=fake), \
         patch("apps.publisher.tasks._resolve_publish_credentials", return_value={"api_key": "k"}):
        reconcile_blotato_posts()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.FAILED
    assert "rejected" in pp.publish_error


@pytest.mark.django_db
def test_reconcile_leaves_in_progress(db):
    from apps.composer.models import PlatformPost
    from apps.publisher.tasks import reconcile_blotato_posts
    pp = _pp(db, "publishing")
    fake = MagicMock()
    fake.check_status.return_value = {"status": "in-progress"}
    with patch("apps.publisher.tasks.get_provider", return_value=fake), \
         patch("apps.publisher.tasks._resolve_publish_credentials", return_value={"api_key": "k"}):
        reconcile_blotato_posts()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.PUBLISHING  # untouched
