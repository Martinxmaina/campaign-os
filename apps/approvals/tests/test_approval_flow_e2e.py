"""End-to-end + regression guard for the approval-by-email flow (Task 8).

Scenario
--------
1. A publisher assigns a post for review (``assign_for_review``).
2. The reviewer GETs the review page and POSTs approve.
3. The publisher receives a "Publish now" email containing a PUBLISH token.
4. The publisher GETs the publish-confirm page and POSTs to publish.
5. ``schedule_now`` runs — ``post.scheduled_at`` is set.
6. The compliance gate is still authoritative: a PlatformPost with no
   ``gate_id`` cannot reach ``published`` via the tokenised path.

Regression guard
----------------
- The one-click Send tests in ``test_send_for_publish.py`` are run as
  part of the same pytest invocation (see Task 8 command).
  This module adds an explicit smoke-check that the ``send_for_publish``
  helper still works after all the approval-by-email machinery is wired in.
"""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.approvals.models import ActionToken, ApprovalAction, ReviewAssignment
from apps.composer.models import PlatformPost, Post


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _review_url(workspace_id, token):
    return reverse("approvals:review", kwargs={"workspace_id": workspace_id, "token": token})


def _publish_url(workspace_id, token):
    return reverse(
        "approvals:review_publish",
        kwargs={"workspace_id": workspace_id, "token": token},
    )


# ---------------------------------------------------------------------------
# Full approval-by-email flow
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_full_approval_by_email_flow(client, workspace, django_user_model, monkeypatch):
    """Full end-to-end: assign → review GET → approve POST → publish GET → publish POST.

    Asserts (in order):
    - assign_for_review sends one email to the reviewer embedding the review URL.
    - GET review page returns 200 with Approve/Decline controls.
    - POST approve → ApprovalAction(APPROVED) + assignment.status=APPROVED +
      post.review_state=approved + PUBLISH token minted + publisher emailed.
    - GET publish confirm page returns 200.
    - POST publish → schedule_now ran (post.scheduled_at set) + PUBLISH token
      consumed so replay is a no-op.
    """
    from apps.approvals import assignment_service, emailer

    # Capture all send_email calls so we can inspect them without real SMTP.
    sent: list[dict] = []

    def _fake_send(to, subject, html):
        sent.append({"to": to, "subject": subject, "html": html})
        return True

    monkeypatch.setattr(emailer, "send_email", _fake_send)

    # ------------------------------------------------------------------
    # Set up: publisher user + post
    # ------------------------------------------------------------------
    publisher = django_user_model.objects.create_user(
        email="e2e-publisher@example.com", password="x", name="E2E Publisher"
    )
    post = Post.objects.create(
        workspace=workspace, title="E2E Test Post", caption="E2E caption"
    )

    # ------------------------------------------------------------------
    # Step 1: assign_for_review
    # ------------------------------------------------------------------
    assignment = assignment_service.assign_for_review(
        post, publisher, "e2e-reviewer@example.com", "E2E Reviewer"
    )

    assert isinstance(assignment, ReviewAssignment)
    assert assignment.status == ReviewAssignment.Status.PENDING
    assert assignment.reviewer_email == "e2e-reviewer@example.com"

    # Exactly one email sent to the reviewer.
    assert len(sent) == 1, f"Expected 1 email after assign, got {len(sent)}"
    assert sent[0]["to"] == "e2e-reviewer@example.com"

    # The review URL (with token) must be embedded in the HTML.
    review_tok = ActionToken.objects.get(
        assignment=assignment, purpose=ActionToken.Purpose.REVIEW
    )
    assert review_tok.token in sent[0]["html"], "Review token not found in email HTML"

    # post.review_state → pending
    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.PENDING

    # ------------------------------------------------------------------
    # Step 2: reviewer GETs the review page
    # ------------------------------------------------------------------
    review_page_url = _review_url(workspace.id, review_tok.token)
    resp = client.get(review_page_url)

    assert resp.status_code == 200
    content = resp.content.decode()
    assert "approve" in content.lower() or "Approve" in content
    assert "decline" in content.lower() or "Decline" in content

    # ------------------------------------------------------------------
    # Step 3: reviewer POSTs approve
    # ------------------------------------------------------------------
    sent.clear()  # reset to check next email separately
    resp = client.post(review_page_url, {"decision": "approve", "reason": ""})

    assert resp.status_code in (200, 302)

    # ApprovalAction(APPROVED) created.
    assert ApprovalAction.objects.filter(
        post=post, action=ApprovalAction.ActionType.APPROVED
    ).exists()

    # Assignment status = APPROVED.
    assignment.refresh_from_db()
    assert assignment.status == ReviewAssignment.Status.APPROVED

    # Post review_state = approved.
    post.refresh_from_db()
    assert post.review_state == Post.ReviewState.APPROVED

    # REVIEW token consumed.
    review_tok.refresh_from_db()
    assert review_tok.used_at is not None

    # PUBLISH token minted.
    publish_tok = ActionToken.objects.get(
        assignment=assignment, purpose=ActionToken.Purpose.PUBLISH
    )
    assert publish_tok.used_at is None  # not yet consumed

    # Publisher emailed (one email with publish URL).
    assert len(sent) == 1, f"Expected 1 email to publisher after approve, got {len(sent)}"
    publisher_email_html = sent[0]["html"]
    assert publish_tok.token in publisher_email_html, (
        "Publish token URL not found in publisher's 'ready to publish' email"
    )

    # ------------------------------------------------------------------
    # Step 4: publisher GETs the publish-confirm page
    # ------------------------------------------------------------------
    publish_page_url = _publish_url(workspace.id, publish_tok.token)
    resp = client.get(publish_page_url)

    assert resp.status_code == 200
    content = resp.content.decode()
    assert "publish" in content.lower()

    # ------------------------------------------------------------------
    # Step 5: publisher POSTs to publish
    # ------------------------------------------------------------------
    assert post.scheduled_at is None
    resp = client.post(publish_page_url)

    assert resp.status_code in (200, 302)

    # schedule_now ran: scheduled_at is set.
    post.refresh_from_db()
    assert post.scheduled_at is not None, "schedule_now must have set scheduled_at"

    # PUBLISH token consumed.
    publish_tok.refresh_from_db()
    assert publish_tok.used_at is not None

    # ------------------------------------------------------------------
    # Step 6: replay of publish token → invalid page, no double-schedule
    # ------------------------------------------------------------------
    first_scheduled_at = post.scheduled_at
    resp = client.post(publish_page_url)

    assert resp.status_code == 200
    content = resp.content.decode()
    assert (
        "no longer valid" in content.lower()
        or "invalid" in content.lower()
        or "expired" in content.lower()
    ), "Consumed PUBLISH token must render the 'link no longer valid' page on replay"

    post.refresh_from_db()
    assert post.scheduled_at == first_scheduled_at, "Replay must not update scheduled_at"


# ---------------------------------------------------------------------------
# Gate authoritative (full-flow variant)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_gate_still_authoritative_after_email_approve(
    client, workspace, django_user_model, social_account, monkeypatch
):
    """After the tokenised publish path schedules the post, the gate is still
    authoritative: a PlatformPost with no gate_id can never reach 'published'.

    This mirrors the gate test in ``test_review_publish.py`` but exercises the
    full approval-by-email path (assign → approve → publish token POST) rather
    than starting from a pre-minted token.
    """
    from apps.approvals import assignment_service, emailer
    from apps.publisher.engine import GateBlockError, PublishEngine

    monkeypatch.setattr(emailer, "send_email", lambda *a, **kw: True)

    publisher = django_user_model.objects.create_user(
        email="gate-e2e@example.com", password="x", name="Gate E2E"
    )
    post = Post.objects.create(
        workspace=workspace, title="Gate E2E Post", caption="Gate caption"
    )
    account = social_account("linkedin")
    pp = PlatformPost.objects.create(
        post=post,
        social_account=account,
        status=PlatformPost.Status.PENDING_REVIEW,
        gate_bypassed=False,
    )
    assert pp.gate_id is None

    # Assign for review → creates REVIEW token.
    assignment = assignment_service.assign_for_review(
        post, publisher, "gate-reviewer@example.com", "Gate Reviewer"
    )
    review_tok = ActionToken.objects.get(
        assignment=assignment, purpose=ActionToken.Purpose.REVIEW
    )

    # Reviewer approves → PUBLISH token minted.
    client.post(_review_url(workspace.id, review_tok.token), {"decision": "approve", "reason": ""})

    publish_tok = ActionToken.objects.get(
        assignment=assignment, purpose=ActionToken.Purpose.PUBLISH
    )

    # Reflect the approval transition on the PlatformPost (pending_review → approved)
    # before the publish-token POST which calls schedule_now.
    pp.refresh_from_db()
    pp.transition_to(PlatformPost.Status.APPROVED)
    pp.save(update_fields=["status", "updated_at"])

    # Publisher triggers publish via token.
    resp = client.post(_publish_url(workspace.id, publish_tok.token))
    assert resp.status_code in (200, 302)

    # schedule_now scheduled the PlatformPost (approved → scheduled).
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.SCHEDULED

    # Gate is authoritative: dispatch must raise GateBlockError.
    engine = PublishEngine.__new__(PublishEngine)
    with pytest.raises(GateBlockError):
        engine._dispatch_to_provider(pp)

    pp.refresh_from_db()
    assert pp.status != PlatformPost.Status.PUBLISHED


# ---------------------------------------------------------------------------
# Regression guard: one-click Send still works
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_one_click_send_regression(workspace, django_user_model):
    """Smoke-check that ``send_for_publish`` (one-click Send) still works after
    the approval-by-email machinery has been wired in.

    This does NOT replace the dedicated tests in ``test_send_for_publish.py``
    — those continue to run in the same pytest invocation.  This guard catches
    a hard import or state break that would prevent the helper from running at
    all.
    """
    from django.utils import timezone
    from apps.approvals.send_actions import send_for_publish
    from apps.members.models import OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization

    # Create an organisation + publisher to satisfy the FK constraints in
    # send_for_publish (review_assignee must be a real workspace member).
    organization = Organization.objects.filter(workspaces=workspace).first()
    if organization is None:
        from apps.organizations.models import Organization
        organization = Organization.objects.create(name="Regression Org")
        workspace.organization = organization
        workspace.save(update_fields=["organization"])

    publisher = django_user_model.objects.create_user(
        email="regression-send@example.com", password="x", name="Regression Send",
        tos_accepted_at=timezone.now(),
    )
    if not OrgMembership.objects.filter(user=publisher, organization=organization).exists():
        OrgMembership.objects.create(
            user=publisher, organization=organization, org_role=OrgMembership.OrgRole.OWNER
        )
    if not WorkspaceMembership.objects.filter(user=publisher, workspace=workspace).exists():
        WorkspaceMembership.objects.create(
            user=publisher, workspace=workspace, workspace_role="owner"
        )
    publisher.last_workspace_id = workspace.id
    publisher.save(update_fields=["last_workspace_id"])

    post = Post.objects.create(
        workspace=workspace,
        title="Regression Send Post",
        caption="One-click send regression",
        review_state="pending",
        review_assignee=publisher,
    )

    send_for_publish(post, publisher)

    post.refresh_from_db()
    assert post.review_state == "approved"
    assert post.scheduled_at is not None
    assert ApprovalAction.objects.filter(post=post, action="approved").exists()
