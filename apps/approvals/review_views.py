"""Public review views for approval-by-email (Task 5 + Task 6).

These views are PUBLIC — no ``login_required``.  They are protected by
single-use signed tokens (``ActionToken``).  CSRF protection is retained
(the ``@csrf_protect`` decorator) to guard against cross-site form
submissions.

URL parameters:
    workspace_id  — UUID; comes from the parent URL pattern
                    ``workspace/<uuid:workspace_id>/``.  Not used for
                    access-control (the token is the secret); included so
                    the URL namespace resolves correctly.
    token         — the raw ``ActionToken.token`` value.
"""
from __future__ import annotations

from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect

from apps.approvals import emailer, tokens as tok_mod
from apps.approvals.models import ActionToken, ApprovalAction, ReviewAssignment
from apps.approvals.utils import abs_url as _abs
from apps.approvals.platform_cards import render_cards
from apps.composer.models import Post
from apps.settings_manager.helpers import get_setting
from django.template.loader import render_to_string
from django.urls import reverse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _publisher_email(assignment):
    """Return the address to notify the publisher.

    Publish notifications go to the workspace's designated publish inbox
    (``review.copy_email``); only if that is unset do we fall back to the
    assigner's own account email.
    """
    post = assignment.post
    configured = get_setting(post.workspace_id, "review.copy_email")
    if configured:
        return configured
    if assignment.assigned_by_id and assignment.assigned_by.email:
        return assignment.assigned_by.email
    return ""


def _render_invalid(request):
    """Render the 'link no longer valid' page."""
    return render(request, "approvals/public/invalid.html", {}, status=200)


# ---------------------------------------------------------------------------
# Public review view (Task 5)
# ---------------------------------------------------------------------------

@csrf_protect
def review(request, workspace_id, token):
    """Public review page — GET shows the post for review; POST records the decision."""
    tok = tok_mod.resolve_token(token, ActionToken.Purpose.REVIEW)
    if tok is None:
        return _render_invalid(request)

    assignment = tok.assignment
    post = assignment.post
    cards_html = render_cards(post)

    if request.method == "GET":
        return render(request, "approvals/public/review.html", {
            "post": post,
            "assignment": assignment,
            "cards": cards_html,
            "token": token,
        })

    # POST — read decision
    decision = request.POST.get("decision", "").strip().lower()
    reason = request.POST.get("reason", "").strip()

    if decision == "approve":
        with transaction.atomic():
            # Re-check token inside the transaction (idempotency guard)
            tok_live = tok_mod.resolve_token(token, ActionToken.Purpose.REVIEW)
            if tok_live is None:
                return _render_invalid(request)

            # Record the approval action
            ApprovalAction.objects.create(
                post=post,
                user=assignment.assigned_by,
                action=ApprovalAction.ActionType.APPROVED,
                comment=reason,
            )

            # Update assignment + post state
            assignment.status = ReviewAssignment.Status.APPROVED
            assignment.decided_at = timezone.now()
            assignment.save(update_fields=["status", "decided_at"])

            post.review_state = Post.ReviewState.APPROVED
            post.save(update_fields=["review_state", "updated_at"])

            # Consume the REVIEW token
            tok_mod.consume(tok_live)

            # Mint a PUBLISH token
            ttl = get_setting(post.workspace_id, "review.token_ttl_days") or 7
            publish_tok = tok_mod.mint_token(
                assignment, ActionToken.Purpose.PUBLISH, ttl_days=int(ttl)
            )

        # Email the publisher (outside the transaction so failures don't rollback)
        publish_url = _abs(
            reverse(
                "approvals:review_publish",
                kwargs={"workspace_id": post.workspace_id, "token": publish_tok.token},
            )
        )
        html = render_to_string(
            "approvals/email/publish.html",
            {"post": post, "cards": cards_html, "publish_url": publish_url},
        )
        publisher_email = _publisher_email(assignment)
        if publisher_email:
            emailer.send_email(
                publisher_email,
                f"Approved and ready to publish: {post.title or post.caption_snippet}",
                html,
            )

        return render(request, "approvals/public/review.html", {
            "post": post,
            "assignment": assignment,
            "cards": cards_html,
            "token": token,
            "success": "approved",
        })

    elif decision == "decline":
        if not reason:
            # Re-render with error — no state change
            return render(request, "approvals/public/review.html", {
                "post": post,
                "assignment": assignment,
                "cards": cards_html,
                "token": token,
                "error": "A reason is required when declining.",
            })

        with transaction.atomic():
            tok_live = tok_mod.resolve_token(token, ActionToken.Purpose.REVIEW)
            if tok_live is None:
                return _render_invalid(request)

            # Record the changes-requested action
            ApprovalAction.objects.create(
                post=post,
                user=assignment.assigned_by,
                action=ApprovalAction.ActionType.CHANGES_REQUESTED,
                comment=reason,
            )

            # Update assignment + post state
            assignment.status = ReviewAssignment.Status.DECLINED
            assignment.reason = reason
            assignment.decided_at = timezone.now()
            assignment.save(update_fields=["status", "reason", "decided_at"])

            post.review_state = Post.ReviewState.CHANGES_REQUESTED
            post.save(update_fields=["review_state", "updated_at"])

            # Consume the token
            tok_mod.consume(tok_live)

        # Email the publisher
        declined_html = render_to_string(
            "approvals/email/declined.html",
            {"post": post, "reason": reason},
        )
        publisher_email = _publisher_email(assignment)
        if publisher_email:
            emailer.send_email(
                publisher_email,
                f"Declined: {post.title or post.caption_snippet}",
                declined_html,
            )

        return render(request, "approvals/public/review.html", {
            "post": post,
            "assignment": assignment,
            "cards": cards_html,
            "token": token,
            "success": "declined",
        })

    else:
        # Unknown decision — re-render
        return render(request, "approvals/public/review.html", {
            "post": post,
            "assignment": assignment,
            "cards": cards_html,
            "token": token,
            "error": "Unknown decision.",
        })


# ---------------------------------------------------------------------------
# Publish-by-token view (Task 6)
# ---------------------------------------------------------------------------

@csrf_protect
def publish(request, workspace_id, token):
    """Public publish-by-token page.

    GET shows a confirm page (with the platform cards). POST consumes the
    single-use PUBLISH token and hands the post to ``schedule_now`` — which
    only schedules; the authoritative compliance gate still runs downstream at
    ``apps/publisher/engine._dispatch_to_provider``, so this path can never
    bypass the gate.
    """
    tok = tok_mod.resolve_token(token, ActionToken.Purpose.PUBLISH)
    if tok is None:
        return _render_invalid(request)

    assignment = tok.assignment
    post = assignment.post
    cards_html = render_cards(post)

    if request.method == "GET":
        return render(request, "approvals/public/publish.html", {
            "post": post,
            "assignment": assignment,
            "cards": cards_html,
            "token": token,
        })

    # POST — consume the token and schedule the post.
    from apps.composer.views import schedule_now

    with transaction.atomic():
        # Re-resolve inside the transaction so a replay can't double-schedule.
        tok_live = tok_mod.resolve_token(token, ActionToken.Purpose.PUBLISH)
        if tok_live is None:
            return _render_invalid(request)
        tok_mod.consume(tok_live)
        schedule_now(post)

    return render(request, "approvals/public/publish.html", {
        "post": post,
        "assignment": assignment,
        "cards": cards_html,
        "token": token,
        "success": True,
    })
