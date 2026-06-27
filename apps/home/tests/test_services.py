import pytest
from datetime import timedelta
from django.utils import timezone

from apps.home.services import performance_summary
from apps.composer.models import Post, PlatformPost
from apps.analytics.models import PostInsightsSnapshot

pytestmark = pytest.mark.django_db


def test_performance_summary_empty_workspace(workspace):
    s = performance_summary(workspace, days=30)
    assert s["has_data"] is False
    assert len(s["series"]) == 30
    assert s["posts_published"] == 0
    assert s["total_reach"] == 0


def test_performance_summary_counts_published_posts_and_series(workspace, social_account, make_post):
    today = timezone.now().date()
    post = make_post(workspace, status="published")
    pp = PlatformPost.objects.create(
        post=post, social_account=social_account,
        status=PlatformPost.Status.PUBLISHED, published_at=timezone.now(),
    )
    PostInsightsSnapshot.objects.create(platform_post=pp, metric_key="engagement", date=today, value=12.0)
    PostInsightsSnapshot.objects.create(platform_post=pp, metric_key="reach", date=today, value=300.0)

    s = performance_summary(workspace, days=30, metric="engagement")
    assert s["has_data"] is True
    assert s["posts_published"] == 1
    assert s["total_reach"] == 300.0
    assert s["series"][-1] == 12.0  # today is the last bucket
    assert any(p["platform"] == social_account.platform for p in s["by_platform"])


# ----------------------------------------------------------------------------
# A3 — action-card services (sign-off, drafts, going-out-soon)
# ----------------------------------------------------------------------------
from apps.home.services import pending_signoff, my_drafts, going_out_soon


def _attach_pp(post, social_account, status):
    """Give ``post`` a single PlatformPost child in ``status``.

    Project idiom: a Post's editorial status is *derived* from its
    ``platform_posts`` children (see ``apps.composer.status.derive_post_status``
    and ``apps/composer/tests/test_studio_query.py``'s ``_post`` helper), so a
    test that needs a specific draft/published post attaches the child itself.
    """
    return PlatformPost.objects.create(
        post=post, social_account=social_account, status=status,
    )


def test_my_drafts_returns_only_my_workspace_drafts(
    workspace, other_workspace, social_account, make_post, make_user_in_workspace
):
    user = make_user_in_workspace(workspace)
    mine = make_post(workspace, status="draft", author=user)
    _attach_pp(mine, social_account, PlatformPost.Status.DRAFT)

    published = make_post(workspace, status="published", author=user)  # not a draft
    _attach_pp(published, social_account, PlatformPost.Status.PUBLISHED)

    # Other-workspace draft (its own social account, so the cross-house wall holds).
    from apps.social_accounts.models import SocialAccount

    other_acct = SocialAccount.objects.create(
        workspace=other_workspace, platform="linkedin",
        account_platform_id="acct-linkedin-other", account_name="Other LinkedIn",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    elsewhere = make_post(other_workspace, status="draft", author=user)
    _attach_pp(elsewhere, other_acct, PlatformPost.Status.DRAFT)

    ids = {p.id for p in my_drafts(workspace, user)}
    assert ids == {mine.id}


def test_going_out_soon_lists_scheduled_within_window(workspace, make_post):
    from django.utils import timezone
    from datetime import timedelta

    soon = make_post(
        workspace, status="scheduled", scheduled_at=timezone.now() + timedelta(days=2)
    )
    make_post(
        workspace, status="scheduled", scheduled_at=timezone.now() + timedelta(days=30)
    )  # outside 7d
    ids = {p.id for p in going_out_soon(workspace, days=7)}
    assert soon.id in ids and len(ids) == 1


def test_pending_signoff_lists_posts_awaiting_review(
    workspace, make_post, make_user_in_workspace
):
    from apps.composer.models import Post

    user = make_user_in_workspace(workspace)
    waiting = make_post(workspace, review_state=Post.ReviewState.PENDING)
    make_post(workspace, review_state=Post.ReviewState.APPROVED)  # already signed off
    ids = {p.id for p in pending_signoff(workspace, user)}
    assert ids == {waiting.id}
