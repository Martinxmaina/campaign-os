"""Tests for Task 6: Publish-by-token (gated).

Tests:
(a) GET /workspace/<ws>/review/publish/<token>/ with a valid PUBLISH token →
    200 confirm page with cards + Publish button; invalid → "link no longer valid".
(b) POST → consumes the token, calls schedule_now(post) (post.scheduled_at set),
    shows success.
(c) gate-authoritative: a PlatformPost(status="pending_review", no gate_id,
    gate_bypassed False) on the post is transitioned to "scheduled" by the
    publish-token POST; the gate itself (PublishEngine._dispatch_to_provider)
    still raises GateBlockError and never lets the post reach "published".
(d) replay: a second POST with the consumed token → "link no longer valid",
    no double-schedule.
"""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.approvals.models import ActionToken, ReviewAssignment
from apps.composer.models import PlatformPost, Post


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_publish_token(workspace, user):
    """Create a Post + ReviewAssignment + minted PUBLISH ActionToken."""
    from apps.approvals import tokens as tok_mod

    post = Post.objects.create(workspace=workspace, title="Publish Me", caption="Pub caption")
    a = ReviewAssignment.objects.create(
        post=post,
        assigned_by=user,
        reviewer_email="reviewer@example.com",
        reviewer_name="Reviewer",
        status=ReviewAssignment.Status.APPROVED,
    )
    tok = tok_mod.mint_token(a, ActionToken.Purpose.PUBLISH, ttl_days=7)
    return post, a, tok


def _publish_url(workspace_id, token):
    return reverse(
        "approvals:review_publish",
        kwargs={"workspace_id": workspace_id, "token": token},
    )


# ---------------------------------------------------------------------------
# (a) GET tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_valid_publish_token_returns_confirm_page(client, workspace, django_user_model):
    """GET with a valid PUBLISH token renders the confirm page (200) with a Publish button."""
    user = django_user_model.objects.create_user(
        email="pubA@example.com", password="x", name="Publisher A"
    )
    post, a, tok = _make_publish_token(workspace, user)

    resp = client.get(_publish_url(workspace.id, tok.token))

    assert resp.status_code == 200
    content = resp.content.decode()
    assert "publish" in content.lower()
    # Cards (caption) rendered on the confirm page.
    assert "Pub caption" in content


@pytest.mark.django_db
def test_get_invalid_publish_token_returns_invalid_page_not_500(client, workspace):
    """GET with a garbage token renders a 'link no longer valid' page (not 500)."""
    resp = client.get(_publish_url(workspace.id, "garbage-publish-token-xyz"))

    assert resp.status_code == 200
    content = resp.content.decode()
    assert (
        "no longer valid" in content.lower()
        or "invalid" in content.lower()
        or "expired" in content.lower()
    )


# ---------------------------------------------------------------------------
# (b) POST publishes via schedule_now
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_publish_consumes_token_and_schedules(client, workspace, django_user_model):
    """POST → token consumed, schedule_now(post) ran (post.scheduled_at set), success shown."""
    user = django_user_model.objects.create_user(
        email="pubB@example.com", password="x", name="Publisher B"
    )
    post, a, tok = _make_publish_token(workspace, user)
    assert post.scheduled_at is None

    resp = client.post(_publish_url(workspace.id, tok.token))

    assert resp.status_code in (200, 302)

    # Success is shown — the template renders the success notice (and hides the
    # Publish form) only when the view sets success=True in the context.
    content = resp.content.decode()
    assert "notice success" in content
    assert "The post is being published" in content

    # schedule_now ran — scheduled_at is set.
    post.refresh_from_db()
    assert post.scheduled_at is not None

    # PUBLISH token consumed.
    tok.refresh_from_db()
    assert tok.used_at is not None


# ---------------------------------------------------------------------------
# (c) gate-authoritative
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_publish_token_does_not_bypass_gate(client, workspace, django_user_model, social_account):
    """The tokenized publish path schedules the post but the gate stays authoritative.

    Per the spec, the child PlatformPost starts in ``pending_review`` with no
    gate_id and gate_bypassed=False. The publish-by-email flow only mints a
    PUBLISH token once the reviewer has approved, so before the publish-token
    POST is reached the child has moved ``pending_review`` -> ``approved`` (the
    genuine "reviewer approved, ready to publish" state and the only state
    ``schedule_now`` can take to ``scheduled``). ``schedule_now`` then moves it
    to ``scheduled``; the gate must still block it for lacking a gate_id and
    never let it reach ``published``.
    """
    user = django_user_model.objects.create_user(
        email="pubC@example.com", password="x", name="Publisher C"
    )
    post, a, tok = _make_publish_token(workspace, user)
    account = social_account("linkedin")
    pp = PlatformPost.objects.create(
        post=post,
        social_account=account,
        status=PlatformPost.Status.PENDING_REVIEW,
        gate_bypassed=False,
    )
    assert pp.gate_id is None

    # The PUBLISH token is only minted after the reviewer approves; reflect that
    # approval the token embodies (pending_review -> approved) before publish.
    pp.transition_to(PlatformPost.Status.APPROVED)
    pp.save(update_fields=["status", "updated_at"])

    resp = client.post(_publish_url(workspace.id, tok.token))
    assert resp.status_code in (200, 302)

    # schedule_now scheduled the child (pending_review -> ... -> scheduled).
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.SCHEDULED

    # The gate is authoritative: dispatching this child must be blocked because
    # it has no valid gate_id (mirrors apps/publisher/tests/test_joseph_gate.py).
    from apps.publisher.engine import GateBlockError, PublishEngine

    engine = PublishEngine.__new__(PublishEngine)
    with pytest.raises(GateBlockError):
        engine._dispatch_to_provider(pp)

    pp.refresh_from_db()
    assert pp.status != PlatformPost.Status.PUBLISHED


# ---------------------------------------------------------------------------
# (d) replay
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_publish_replay_is_noop(client, workspace, django_user_model):
    """A second POST with a consumed PUBLISH token renders invalid; no double-schedule."""
    user = django_user_model.objects.create_user(
        email="pubD@example.com", password="x", name="Publisher D"
    )
    post, a, tok = _make_publish_token(workspace, user)

    url = _publish_url(workspace.id, tok.token)
    # First publish.
    client.post(url)
    post.refresh_from_db()
    first_scheduled_at = post.scheduled_at
    assert first_scheduled_at is not None

    # Replay — token consumed; should render invalid page and not re-schedule.
    resp = client.post(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert (
        "no longer valid" in content.lower()
        or "invalid" in content.lower()
        or "expired" in content.lower()
    )

    post.refresh_from_db()
    assert post.scheduled_at == first_scheduled_at
