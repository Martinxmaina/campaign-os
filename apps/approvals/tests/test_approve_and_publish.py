"""Reviewer 'Approve & publish now' — approve and publish in one step (gated)."""
import pytest
from django.urls import reverse

from apps.approvals.models import ActionToken, ReviewAssignment
from apps.composer.models import Post


def _make_review_token(workspace, user):
    from apps.approvals import tokens as tok_mod

    post = Post.objects.create(workspace=workspace, title="Review Me", caption="Cap")
    a = ReviewAssignment.objects.create(
        post=post, assigned_by=user, reviewer_email="r@example.com", reviewer_name="R"
    )
    tok = tok_mod.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)
    return post, a, tok


def _review_url(ws_id, token):
    return reverse("approvals:review", kwargs={"workspace_id": ws_id, "token": token})


@pytest.mark.django_db
def test_approve_publish_approves_and_schedules_directly(client, workspace, django_user_model):
    user = django_user_model.objects.create_user(email="ap@example.com", password="x", name="Owner")
    post, a, tok = _make_review_token(workspace, user)
    assert post.scheduled_at is None

    resp = client.post(_review_url(workspace.id, tok.token), {"decision": "approve_publish"})
    assert resp.status_code in (200, 302)

    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.APPROVED
    assert post.scheduled_at is not None  # schedule_now ran (gate still runs at dispatch)
    a.refresh_from_db()
    assert a.status == ReviewAssignment.Status.APPROVED
    tok.refresh_from_db()
    assert tok.used_at is not None  # REVIEW token consumed
    # Direct-publish path mints NO separate PUBLISH token.
    assert not ActionToken.objects.filter(assignment=a, purpose=ActionToken.Purpose.PUBLISH).exists()


@pytest.mark.django_db
def test_plain_approve_still_routes_to_owner(client, workspace, django_user_model):
    """Regression: 'approve' (not approve_publish) keeps the two-step flow."""
    user = django_user_model.objects.create_user(email="ap2@example.com", password="x", name="Owner2")
    post, a, tok = _make_review_token(workspace, user)

    resp = client.post(_review_url(workspace.id, tok.token), {"decision": "approve"})
    assert resp.status_code in (200, 302)

    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.APPROVED
    assert post.scheduled_at is None  # NOT published directly
    assert ActionToken.objects.filter(assignment=a, purpose=ActionToken.Purpose.PUBLISH).exists()
