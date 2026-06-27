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
