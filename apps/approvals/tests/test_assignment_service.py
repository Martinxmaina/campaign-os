"""Tests for apps.approvals.assignment_service — Task 4."""

import pytest
from django.core import mail

from apps.composer.models import Post
from apps.approvals.models import ReviewAssignment, ActionToken


@pytest.mark.django_db
def test_assign_for_review_creates_assignment_and_sends_email(
    workspace, django_user_model, monkeypatch
):
    """assign_for_review should:
    - create a ReviewAssignment (status PENDING)
    - mint a REVIEW ActionToken
    - set post.review_state to PENDING
    - send exactly one email to the reviewer
    - embed the review URL (containing the token) in the HTML body
    """
    from apps.approvals import assignment_service, emailer

    # Capture send_email calls
    sent = []

    def _fake_send_email(to, subject, html):
        sent.append({"to": to, "subject": subject, "html": html})
        return True

    monkeypatch.setattr(emailer, "send_email", _fake_send_email)

    user = django_user_model.objects.create_user(
        email="publisher@x.co", password="x", name="Publisher"
    )
    post = Post.objects.create(workspace=workspace, title="Test Post", caption="Some caption")

    assignment = assignment_service.assign_for_review(
        post, user, "rev@x.co", "Rev"
    )

    # ReviewAssignment created with PENDING status
    assert isinstance(assignment, ReviewAssignment)
    assert assignment.status == ReviewAssignment.Status.PENDING
    assert assignment.reviewer_email == "rev@x.co"
    assert assignment.reviewer_name == "Rev"
    assert assignment.assigned_by == user

    # REVIEW ActionToken minted
    tok = ActionToken.objects.get(assignment=assignment, purpose=ActionToken.Purpose.REVIEW)
    assert tok.token  # non-empty
    assert tok.used_at is None

    # post.review_state set to PENDING
    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.PENDING

    # Exactly one email sent
    assert len(sent) == 1
    assert sent[0]["to"] == "rev@x.co"

    # Review URL containing the minted token appears in the HTML
    html = sent[0]["html"]
    assert tok.token in html
