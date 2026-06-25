"""Tests for Task 5: Public review page (approve/decline).

Tests:
(a) GET /workspace/<ws>/review/<token>/ returns 200 with cards + Approve/Decline;
    invalid token → 200 "link no longer valid" page (not 500).
(b) POST approve → ApprovalAction(APPROVED), assignment.status=APPROVED,
    post.review_state="approved", PUBLISH token minted, publisher emailed,
    token consumed (replay is a no-op).
(c) POST decline with empty reason → re-renders with error, no state change;
    with reason → DECLINED + reason, post.review_state="changes_requested",
    publisher emailed.
"""

import pytest
from django.core import mail
from django.urls import reverse

from apps.approvals.models import ActionToken, ApprovalAction, ReviewAssignment
from apps.composer.models import Post


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assignment(workspace, user):
    """Create a Post + ReviewAssignment for *user* in *workspace*."""
    post = Post.objects.create(workspace=workspace, title="Review Me", caption="Test caption")
    a = ReviewAssignment.objects.create(
        post=post,
        assigned_by=user,
        reviewer_email="reviewer@example.com",
        reviewer_name="Reviewer",
    )
    return post, a


def _review_url(workspace_id, token):
    return reverse("approvals:review", kwargs={"workspace_id": workspace_id, "token": token})


# ---------------------------------------------------------------------------
# (a) GET tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_valid_token_returns_review_page(client, workspace, django_user_model, monkeypatch):
    """GET with a valid REVIEW token renders the review page (200) with cards and action buttons."""
    from apps.approvals import tokens as tok_mod

    user = django_user_model.objects.create_user(
        email="pub@example.com", password="x", name="Publisher"
    )
    post, a = _make_assignment(workspace, user)
    tok = tok_mod.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)

    url = _review_url(workspace.id, tok.token)
    resp = client.get(url)

    assert resp.status_code == 200
    content = resp.content.decode()
    # Page must offer Approve and Decline actions.
    assert "approve" in content.lower() or "Approve" in content
    assert "decline" in content.lower() or "Decline" in content


@pytest.mark.django_db
def test_get_invalid_token_returns_invalid_page_not_500(client, workspace):
    """GET with a garbage token renders a 'link no longer valid' page (not 500)."""
    url = _review_url(workspace.id, "totally-invalid-token-xyz")
    resp = client.get(url)

    assert resp.status_code == 200
    content = resp.content.decode()
    assert "no longer valid" in content.lower() or "invalid" in content.lower() or "expired" in content.lower()


# ---------------------------------------------------------------------------
# (b) POST approve
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_approve_records_action_and_emails_publisher(client, workspace, django_user_model, monkeypatch):
    """POST approve → ApprovalAction(APPROVED) + assignment APPROVED + post.review_state=approved +
    PUBLISH token minted + publisher emailed; token consumed so replay is a no-op.
    """
    from apps.approvals import emailer, tokens as tok_mod

    sent = []

    def _fake_send(to, subject, html):
        sent.append({"to": to, "subject": subject, "html": html})
        return True

    monkeypatch.setattr(emailer, "send_email", _fake_send)

    user = django_user_model.objects.create_user(
        email="pub2@example.com", password="x", name="Publisher2"
    )
    post, a = _make_assignment(workspace, user)
    tok = tok_mod.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)

    url = _review_url(workspace.id, tok.token)
    resp = client.post(url, {"decision": "approve", "reason": ""})

    # Should return 200 success or redirect.
    assert resp.status_code in (200, 302)

    # ApprovalAction created with APPROVED
    assert ApprovalAction.objects.filter(
        post=post, action=ApprovalAction.ActionType.APPROVED
    ).exists()

    # Assignment status updated
    a.refresh_from_db()
    assert a.status == ReviewAssignment.Status.APPROVED

    # Post review_state updated
    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.APPROVED

    # PUBLISH token minted
    assert ActionToken.objects.filter(
        assignment=a, purpose=ActionToken.Purpose.PUBLISH
    ).exists()

    # Publisher emailed
    assert len(sent) == 1

    # REVIEW token consumed
    tok.refresh_from_db()
    assert tok.used_at is not None


@pytest.mark.django_db
def test_approve_replay_is_noop(client, workspace, django_user_model, monkeypatch):
    """A second POST with a consumed REVIEW token renders invalid page; no double-action."""
    from apps.approvals import emailer, tokens as tok_mod

    monkeypatch.setattr(emailer, "send_email", lambda *a, **kw: True)

    user = django_user_model.objects.create_user(
        email="pub3@example.com", password="x", name="Publisher3"
    )
    post, a = _make_assignment(workspace, user)
    tok = tok_mod.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)

    url = _review_url(workspace.id, tok.token)
    # First approve
    client.post(url, {"decision": "approve", "reason": ""})
    action_count_before = ApprovalAction.objects.filter(post=post).count()

    # Replay — token is consumed; should render invalid page
    resp = client.post(url, {"decision": "approve", "reason": ""})
    assert resp.status_code == 200
    content = resp.content.decode()
    assert (
        "no longer valid" in content.lower()
        or "invalid" in content.lower()
        or "expired" in content.lower()
    )
    # No extra action created
    assert ApprovalAction.objects.filter(post=post).count() == action_count_before


# ---------------------------------------------------------------------------
# (c) POST decline
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_decline_empty_reason_rerenders_with_error(client, workspace, django_user_model, monkeypatch):
    """POST decline with no reason re-renders the review page with an error; state unchanged."""
    from apps.approvals import emailer, tokens as tok_mod

    monkeypatch.setattr(emailer, "send_email", lambda *a, **kw: True)

    user = django_user_model.objects.create_user(
        email="pub4@example.com", password="x", name="Publisher4"
    )
    post, a = _make_assignment(workspace, user)
    tok = tok_mod.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)

    url = _review_url(workspace.id, tok.token)
    resp = client.post(url, {"decision": "decline", "reason": ""})

    # Re-renders (200) with an error message.
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "reason" in content.lower() or "required" in content.lower() or "error" in content.lower()

    # State unchanged — assignment still PENDING; post.review_state still whatever it was before
    a.refresh_from_db()
    assert a.status == ReviewAssignment.Status.PENDING
    post.refresh_from_db()
    assert post.review_state not in (
        Post.ReviewState.APPROVED,
        Post.ReviewState.CHANGES_REQUESTED,
        Post.ReviewState.REJECTED,
    )


@pytest.mark.django_db
def test_post_decline_with_reason_records_and_emails(client, workspace, django_user_model, monkeypatch):
    """POST decline with a reason → DECLINED + reason + post.review_state=changes_requested + publisher emailed."""
    from apps.approvals import emailer, tokens as tok_mod

    sent = []

    def _fake_send(to, subject, html):
        sent.append({"to": to, "subject": subject, "html": html})
        return True

    monkeypatch.setattr(emailer, "send_email", _fake_send)

    user = django_user_model.objects.create_user(
        email="pub5@example.com", password="x", name="Publisher5"
    )
    post, a = _make_assignment(workspace, user)
    tok = tok_mod.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)

    url = _review_url(workspace.id, tok.token)
    resp = client.post(url, {"decision": "decline", "reason": "Needs more polish"})

    assert resp.status_code in (200, 302)

    # ApprovalAction with CHANGES_REQUESTED
    assert ApprovalAction.objects.filter(
        post=post, action=ApprovalAction.ActionType.CHANGES_REQUESTED
    ).exists()

    # Assignment declined + reason saved
    a.refresh_from_db()
    assert a.status == ReviewAssignment.Status.DECLINED
    assert "polish" in a.reason

    # Post review_state = changes_requested
    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.CHANGES_REQUESTED

    # Publisher emailed
    assert len(sent) == 1

    # Token consumed
    tok.refresh_from_db()
    assert tok.used_at is not None
