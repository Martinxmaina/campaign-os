"""Tests for Task 7: assign-for-review entry UI + token_ttl_days setting.

Tests:
(a) POST to the assign endpoint with {reviewer_email, reviewer_name} for a post
    (as the publisher) → 302/200, ReviewAssignment created (PENDING) + one email sent.
(b) Permission: only a workspace member with approve_posts (or post author) can assign.
    Non-members get 302 (redirect to login) or 403.
(c) review.token_ttl_days default is 7 (get_setting returns 7 when no override).
(d) Post author bypass: a workspace member who is the post's author may assign
    even without the approve_posts permission.
"""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.approvals.models import ReviewAssignment
from apps.composer.models import Post
from apps.members.models import WorkspaceMembership, OrgMembership


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def publisher(db, django_user_model, organization, workspace):
    """A workspace owner who can approve_posts."""
    u = django_user_model.objects.create_user(
        email="publisher@example.com", password="x", name="Publisher",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.OWNER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="owner")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    return u


@pytest.fixture
def post_for_review(db, workspace):
    """A draft post in the workspace with no author set."""
    return Post.objects.create(workspace=workspace, title="Draft Post", caption="Some caption")


def _assign_url(workspace_id, post_id):
    return reverse("approvals:assign_review", kwargs={"workspace_id": workspace_id, "post_id": post_id})


# ---------------------------------------------------------------------------
# (a) POST assigns reviewer and sends email
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_assign_creates_assignment_and_sends_email(client, workspace, publisher, post_for_review, monkeypatch):
    """POST reviewer_email + reviewer_name → ReviewAssignment(PENDING) + one email sent."""
    from apps.approvals import emailer

    sent = []

    def _fake_send(to, subject, html):
        sent.append({"to": to, "subject": subject, "html": html})
        return True

    monkeypatch.setattr(emailer, "send_email", _fake_send)

    client.force_login(publisher)
    url = _assign_url(workspace.id, post_for_review.id)
    resp = client.post(url, {
        "reviewer_email": "reviewer@example.com",
        "reviewer_name": "Reviewer Name",
    })

    assert resp.status_code in (200, 302), f"Unexpected status {resp.status_code}"

    assignment = ReviewAssignment.objects.get(post=post_for_review)
    assert assignment.reviewer_email == "reviewer@example.com"
    assert assignment.reviewer_name == "Reviewer Name"
    assert assignment.status == ReviewAssignment.Status.PENDING

    assert len(sent) == 1, f"Expected 1 email, got {len(sent)}"
    assert sent[0]["to"] == "reviewer@example.com"


# ---------------------------------------------------------------------------
# (b) Permission: non-member / viewer cannot assign
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_non_member_cannot_assign(client, workspace, post_for_review):
    """An unauthenticated user is redirected to login."""
    resp = client.post(
        _assign_url(workspace.id, post_for_review.id),
        {"reviewer_email": "x@x.co", "reviewer_name": "X"},
    )
    # Unauthenticated → redirect to login
    assert resp.status_code == 302
    assert "login" in resp["Location"] or "accounts" in resp["Location"]


@pytest.mark.django_db
def test_member_without_approve_posts_cannot_assign(
    client, workspace, post_for_review, django_user_model, organization
):
    """A viewer-role member (approve_posts=False) who is NOT the post author cannot assign."""
    u = django_user_model.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    # 'viewer' has approve_posts=False per BUILTIN_ROLE_PERMISSIONS
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="viewer")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])

    client.force_login(u)
    resp = client.post(
        _assign_url(workspace.id, post_for_review.id),
        {"reviewer_email": "x@x.co", "reviewer_name": "X"},
    )
    assert resp.status_code in (302, 403), f"Expected 302/403, got {resp.status_code}"
    # No assignment should have been created
    assert not ReviewAssignment.objects.filter(post=post_for_review).exists()


# ---------------------------------------------------------------------------
# (c) review.token_ttl_days default = 7
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_review_token_ttl_days_default(workspace):
    """get_setting returns 7 for review.token_ttl_days when no override is set."""
    from apps.settings_manager.helpers import get_setting

    value = get_setting(workspace.id, "review.token_ttl_days")
    assert value == 7, f"Expected 7, got {value!r}"


# ---------------------------------------------------------------------------
# (d) Post-author bypass: author without approve_posts can still assign
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_post_author_can_assign_without_approve_posts(
    client, workspace, django_user_model, organization, monkeypatch
):
    """A viewer-role member who is the post's author may assign even without approve_posts."""
    from apps.approvals import emailer

    sent = []

    def _fake_send(to, subject, html):
        sent.append({"to": to, "subject": subject, "html": html})
        return True

    monkeypatch.setattr(emailer, "send_email", _fake_send)

    author = django_user_model.objects.create_user(
        email="author@example.com", password="x", name="Author",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(user=author, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    # viewer role has approve_posts=False
    WorkspaceMembership.objects.create(user=author, workspace=workspace, workspace_role="viewer")
    author.last_workspace_id = workspace.id
    author.save(update_fields=["last_workspace_id"])

    # Create a post authored by this user
    authored_post = Post.objects.create(
        workspace=workspace,
        title="Author's Post",
        caption="Written by the author",
        author=author,
    )

    client.force_login(author)
    resp = client.post(
        _assign_url(workspace.id, authored_post.id),
        {
            "reviewer_email": "ext@example.com",
            "reviewer_name": "External Reviewer",
        },
    )

    # Author bypass must succeed (200 or 302)
    assert resp.status_code in (200, 302), (
        f"Post author should be allowed to assign; got {resp.status_code}"
    )

    assignment = ReviewAssignment.objects.get(post=authored_post)
    assert assignment.reviewer_email == "ext@example.com"
    assert assignment.status == ReviewAssignment.Status.PENDING
    assert len(sent) == 1
