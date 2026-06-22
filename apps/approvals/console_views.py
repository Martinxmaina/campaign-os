"""AI Approvals — Django-backed queue for HERALD-drafted Posts, routed by owner."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.approvals.models import ApprovalAction
from apps.composer.models import Post


def _is_ws_admin(request):
    # RBACMiddleware already resolves the WorkspaceMembership (with workspace_role
    # and custom_role select_related), so reuse it instead of re-querying.
    m = getattr(request, "workspace_membership", None)
    return bool(m and m.workspace_role in ("owner", "admin"))


def post_is_publishable(post, user, perms):
    """Single source of truth for "can this user one-tap Publish *post*?".

    Mirrors ``apps.composer.views.publish_post``: an APPROVED post is
    publishable by any member (the untouchable gate is the safety net), and a
    human author who holds ``publish_directly`` may publish their own post
    directly. Used by the Content Studio surfaces to decide when to render the
    Publish action — it never publishes and never touches the gate.
    """
    perms = perms or {}
    is_approved = post.review_state == Post.ReviewState.APPROVED
    is_human_direct = post.author_id == getattr(user, "id", None) and perms.get(
        "publish_directly", False
    )
    return bool(is_approved or is_human_direct)


@login_required
def ai_approvals(request):
    ws = getattr(request, "workspace", None)
    qs = Post.objects.none()
    if ws is not None:
        qs = Post.objects.filter(workspace=ws, review_state=Post.ReviewState.PENDING)
        if not _is_ws_admin(request):
            qs = qs.filter(review_assignee=request.user)
        qs = qs.select_related("review_assignee").order_by("-updated_at")
    return render(request, "console/approvals.html", {"items": list(qs[:200]), "down": False})


@login_required
@require_POST
def approval_decide(request, approval_id):
    """approval_id is a Post UUID (the queue lists Posts)."""
    ws = getattr(request, "workspace", None)
    post = get_object_or_404(Post, id=approval_id, workspace=ws)

    # Authorization: workspace scope alone is not enough. Only the assigned
    # reviewer or a workspace admin/owner may decide on a post. Without this,
    # any non-admin member could POST a crafted approval_id to act on a post
    # not assigned to them.
    if not (_is_ws_admin(request) or post.review_assignee_id == request.user.id):
        return HttpResponseForbidden("You are not authorized to decide on this post.")

    decision = request.POST.get("decision", "")

    if decision == "approve":
        post.review_state = Post.ReviewState.APPROVED
        ApprovalAction.objects.create(post=post, user=request.user, action=ApprovalAction.ActionType.APPROVED)
        # Move any pending_review children toward approved so the publish path can run.
        post.platform_posts.filter(status="pending_review").update(status="approved")
    elif decision == "changes":
        post.review_state = Post.ReviewState.CHANGES_REQUESTED
        ApprovalAction.objects.create(post=post, user=request.user, action=ApprovalAction.ActionType.CHANGES_REQUESTED,
                                      comment=request.POST.get("comment", ""))
    elif decision == "reject":
        post.review_state = Post.ReviewState.REJECTED
        ApprovalAction.objects.create(post=post, user=request.user, action=ApprovalAction.ActionType.REJECTED)
    post.save(update_fields=["review_state", "updated_at"])
    return redirect("console:approvals")
