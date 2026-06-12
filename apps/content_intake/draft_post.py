# apps/content_intake/draft_post.py
"""Create/return an editable composer Post for an intake item at draft-time.

So 'Edit' opens the existing draft in the full composer instead of only after
approval. Reuses apps.approvals.intake_publish.create_post_from_content for the
content-item path (which also creates PlatformPosts for connected channels).
"""
from __future__ import annotations

from apps.common.safe import safe_get
from apps.approvals.intake_publish import create_post_from_content
from apps.composer.models import Post
from apps.content_intake.owner_routing import resolve_reviewer


def _route_for_review(post, intake):
    """Assign the intake's resolved reviewer to the draft Post and file the
    initial SUBMITTED approval action, so the routing decision is both
    queryable (on the Post) and auditable (in the approval log).

    Assignment intent lives on ``Post.review_assignee`` / ``Post.review_state``
    — the authoritative, queryable source of truth — NOT on "does an approval
    row exist yet". That keeps re-routing decoupled from the approval log: a
    later resubmission/decision can't suppress assignment, and a post whose
    owner legitimately changes is re-routed to the new reviewer.

    Idempotency / re-routing:
      * If the resolved reviewer is unchanged, this is a no-op (no duplicate
        SUBMITTED action, no redundant write).
      * If the reviewer changes while the post is still awaiting first review
        (review_state in {NONE, PENDING}), re-point ``review_assignee`` to the
        new reviewer.
      * Once a human has acted (state APPROVED/CHANGES_REQUESTED/REJECTED), the
        review_state is left alone; we never reopen a decided post here.

    The SUBMITTED ApprovalAction is filed exactly once — on the transition out
    of NONE — so the submission timeline isn't duplicated across re-ensures.

    If no reviewer resolves (e.g. an empty workspace), we skip silently rather
    than block draft creation.
    """
    from apps.approvals.models import ApprovalAction
    from apps.composer.models import Post

    reviewer = resolve_reviewer(intake)
    if reviewer is None:
        return post

    open_states = (Post.ReviewState.NONE, Post.ReviewState.PENDING)
    update_fields = []

    # Re-route only while the post is still awaiting first human review.
    if post.review_state in open_states and post.review_assignee_id != reviewer.id:
        post.review_assignee = reviewer
        update_fields.append("review_assignee")

    first_assignment = post.review_state == Post.ReviewState.NONE
    if first_assignment:
        post.review_state = Post.ReviewState.PENDING
        update_fields.append("review_state")

    if update_fields:
        post.save(update_fields=update_fields)

    # File the SUBMITTED action exactly once — on the first assignment.
    if first_assignment:
        ApprovalAction.objects.create(
            post=post,
            user=reviewer,
            action=ApprovalAction.ActionType.SUBMITTED,
        )
    return post


def ensure_draft_post(intake):
    """Return the intake's editable Post, creating it from the HERALD draft if needed."""
    if intake.post_id:
        return _route_for_review(intake.post, intake)

    content = None
    if intake.herald_content_id:
        content = safe_get(f"/content/items/{intake.herald_content_id}", default=None)

    if content:
        return _route_for_review(create_post_from_content(content, intake), intake)

    # Content not ready yet — create a minimal Post from the intake itself so the
    # composer has something to open; caption refreshes when the draft lands.
    post = Post.objects.create(
        workspace=intake.workspace,
        title=(intake.angle or intake.pillar_theme or intake.external_id)[:255],
        caption=intake.angle or intake.proof_point or "",
    )
    intake.post = post
    intake.save(update_fields=["post", "updated_at"])
    return _route_for_review(post, intake)
