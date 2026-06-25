import pytest
from django.utils import timezone
from datetime import timedelta
from apps.composer.models import Post
from apps.approvals.models import ReviewAssignment, ActionToken
from apps.approvals import tokens


@pytest.mark.django_db
def test_mint_and_resolve_review_token(workspace, django_user_model):
    u = django_user_model.objects.create_user(email="m@x.co", password="x", name="M")
    post = Post.objects.create(workspace=workspace, title="P", caption="c")
    a = ReviewAssignment.objects.create(post=post, assigned_by=u,
        reviewer_email="rev@x.co", reviewer_name="Rev")
    t = tokens.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)
    assert t.token and t.expires_at > timezone.now()
    assert tokens.resolve_token(t.token, ActionToken.Purpose.REVIEW) == t


@pytest.mark.django_db
def test_used_and_expired_tokens_rejected(workspace, django_user_model):
    u = django_user_model.objects.create_user(email="m2@x.co", password="x", name="M")
    post = Post.objects.create(workspace=workspace, title="P", caption="c")
    a = ReviewAssignment.objects.create(post=post, assigned_by=u, reviewer_email="r@x.co")
    t = tokens.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)
    tokens.consume(t)
    assert tokens.resolve_token(t.token, ActionToken.Purpose.REVIEW) is None
    t2 = tokens.mint_token(a, ActionToken.Purpose.PUBLISH, ttl_days=7)
    t2.expires_at = timezone.now() - timedelta(seconds=1); t2.save(update_fields=["expires_at"])
    assert tokens.resolve_token(t2.token, ActionToken.Purpose.PUBLISH) is None
