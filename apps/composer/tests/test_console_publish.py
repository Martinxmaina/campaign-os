"""Console Drafts → Post → gate → publish bridge (make the content flow work)."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.approvals.intake_publish import ensure_post_from_content_item
from apps.composer.console_publish import publish_content_item
from apps.composer.models import PlatformPost, Post


@pytest.fixture
def workspace(db):
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    return Workspace.objects.create(organization=org, name="WAIIS")


@pytest.fixture
def connected_account(workspace):
    from apps.social_accounts.models import SocialAccount
    return SocialAccount.objects.create(
        workspace=workspace, platform="linkedin",
        account_platform_id="li-1", account_name="AfCEN",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )


CONTENT = {"id": "c-123", "title": "Fund the talent", "body": "Africa's AI talent is here.",
           "track": "ai10bn", "gate_id": "g-1", "gate_verdict": "pass"}


@pytest.mark.django_db
def test_ensure_post_is_idempotent_and_makes_platform_posts(workspace, connected_account):
    p1 = ensure_post_from_content_item(CONTENT, workspace)
    p2 = ensure_post_from_content_item(CONTENT, workspace)  # re-fire
    assert p1.id == p2.id  # same Post, not a duplicate
    assert Post.objects.filter(workspace=workspace).count() == 1
    assert p1.caption == "Africa's AI talent is here."
    assert f"herald:{CONTENT['id']}" in p1.tags
    assert p1.platform_posts.count() == 1  # one connected account


@pytest.mark.django_db
def test_publish_blocked_when_no_connected_account(workspace):
    res = publish_content_item(CONTENT, workspace, author=None)
    assert res["ok"] is False
    assert res["reason"] == "no_accounts"


@pytest.mark.django_db
def test_publish_surfaces_gate_block_and_does_not_schedule(workspace, connected_account):
    blocked = {"verdict": "block", "findings": [{"rule": "unverified_claim", "msg": "no source"}]}
    with patch("apps.composer.console_publish.check_gate", return_value=blocked):
        res = publish_content_item(CONTENT, workspace, author=None)
    assert res["ok"] is False
    assert res["reason"] == "gate_blocked"
    assert res["findings"]
    # nothing was scheduled — the post's platform posts stay DRAFT, no gate_id
    pp = PlatformPost.objects.get(post_id=res["post_id"])
    assert pp.status == PlatformPost.Status.DRAFT
    assert pp.gate_id is None


@pytest.mark.django_db
def test_publish_now_runs_the_gate_then_publishes(workspace, connected_account):
    ok = {"verdict": "pass", "gate_id": "11111111-1111-1111-1111-111111111111",
          "content_hash": "abc", "findings": []}
    with patch("apps.composer.console_publish.check_gate", return_value=ok), \
         patch("apps.publisher.engine.PublishEngine.poll_and_publish", return_value=1) as pub:
        res = publish_content_item(CONTENT, workspace, author=None)
    assert res["ok"] is True
    assert res["scheduled"] is False
    pub.assert_called_once()  # a real publish cycle ran (gate re-verifies there)
    pp = PlatformPost.objects.get(post_id=res["post_id"])
    assert str(pp.gate_id) == ok["gate_id"]
    assert pp.content_hash  # stamped from canonical_content_hash(caption)
    assert pp.scheduled_at is not None


@pytest.mark.django_db
def test_schedule_future_does_not_publish_now(workspace, connected_account):
    ok = {"verdict": "pass", "gate_id": "11111111-1111-1111-1111-111111111111",
          "content_hash": "abc", "findings": []}
    future = timezone.now() + timedelta(days=2)
    with patch("apps.composer.console_publish.check_gate", return_value=ok), \
         patch("apps.publisher.engine.PublishEngine.poll_and_publish", return_value=0) as pub:
        res = publish_content_item(CONTENT, workspace, author=None, scheduled_at=future)
    assert res["ok"] is True
    assert res["scheduled"] is True
    pub.assert_not_called()  # scheduled for later — the beat cycle will publish
    pp = PlatformPost.objects.get(post_id=res["post_id"])
    assert pp.status == PlatformPost.Status.SCHEDULED
