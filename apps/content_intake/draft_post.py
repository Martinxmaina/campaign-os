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
    """Record a SUBMITTED approval action assigned to the intake's resolved
    reviewer, so the routing decision has a real, auditable runtime effect.

    Idempotent: a draft Post may be opened/ensured many times, so we only file
    the submission once (when the Post has no approval actions yet). If no
    reviewer resolves (e.g. an empty workspace), we skip silently rather than
    block draft creation.
    """
    from apps.approvals.models import ApprovalAction

    if post.approval_actions.exists():
        return post
    reviewer = resolve_reviewer(intake)
    if reviewer is None:
        return post
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
