"""assign_for_review service — Task 4.

Creates a ReviewAssignment, mints a REVIEW token, updates the post's
review_state to PENDING, and emails the reviewer with the review URL.
"""
from __future__ import annotations

import logging

from django.template.loader import render_to_string
from django.urls import reverse

from apps.composer.models import Post
from apps.settings_manager.helpers import get_setting

from . import emailer, tokens
from .models import ActionToken, ReviewAssignment
from .platform_cards import render_cards
from .utils import abs_url

logger = logging.getLogger(__name__)


# Keep a module-local alias so existing internal callers are not broken.
_abs = abs_url


def assign_for_review(
    post,
    assigned_by,
    reviewer_email: str,
    reviewer_name: str = "",
) -> ReviewAssignment:
    """Create a ReviewAssignment, mint a token, update post state, and email the reviewer.

    Args:
        post: The :class:`~apps.composer.models.Post` to review.
        assigned_by: The User initiating the assignment (may be None for system).
        reviewer_email: Email address of the external reviewer.
        reviewer_name: Display name for the reviewer (optional).

    Returns:
        The newly created :class:`~apps.approvals.models.ReviewAssignment`.
    """
    # 1. Create the ReviewAssignment.
    a = ReviewAssignment.objects.create(
        post=post,
        assigned_by=assigned_by,
        reviewer_email=reviewer_email,
        reviewer_name=reviewer_name or "",
    )

    # 2. Update post.review_state → PENDING.
    #    Guard review_assignee: the field is a FK to User; only set it when
    #    assigned_by is non-None to avoid integrity errors.
    update_fields = ["review_state", "updated_at"]
    post.review_state = Post.ReviewState.PENDING
    if assigned_by is not None:
        post.review_assignee = assigned_by
        update_fields.append("review_assignee")
    post.save(update_fields=update_fields)

    # 3. Mint the REVIEW token.
    ttl = get_setting(post.workspace_id, "review.token_ttl_days") or 7
    tok = tokens.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=int(ttl))

    # 4. Build the review URL and render the email.
    # The approvals app is mounted under workspace/<workspace_id>/, so the
    # review route requires workspace_id as the first path segment.
    review_url = _abs(
        reverse("approvals:review", kwargs={"workspace_id": post.workspace_id, "token": tok.token})
    )
    html = render_to_string(
        "approvals/email/review.html",
        {
            "post": post,
            "cards": render_cards(post),
            "review_url": review_url,
            "reviewer_name": reviewer_name,
        },
    )

    # 5. Send the email (best-effort; failure is logged but never raises).
    subject = f"Review requested: {post.title or post.caption_snippet}"
    emailer.send_email(reviewer_email, subject, html)

    return a
