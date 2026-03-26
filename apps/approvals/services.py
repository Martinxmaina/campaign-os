"""Approval workflow business logic.

All approval actions go through these functions to enforce the state machine,
create audit trail records, and dispatch notifications.
"""

import logging

from django.db import transaction

from apps.composer.models import Post
from apps.members.models import WorkspaceMembership
from apps.notifications.engine import notify
from apps.notifications.models import EventType

from .models import ApprovalAction, ApprovalReminder

logger = logging.getLogger(__name__)


def submit_for_review(post, user, workspace):
    """Submit a post for internal review.

    Transitions draft/changes_requested → pending_review.
    Notifies all workspace members with approve_posts permission.
    """
    with transaction.atomic():
        post.transition_to("pending_review")
        post.save(update_fields=["status", "updated_at"])

        ApprovalAction.objects.create(
            post=post,
            user=user,
            action=ApprovalAction.ActionType.SUBMITTED,
        )

        # Reset reminder tracking for this stage
        ApprovalReminder.objects.update_or_create(
            post=post,
            stage="pending_review",
            defaults={"reminder_count": 0, "last_reminder_at": None, "escalated": False},
        )

    # Notify all reviewers (members with approve_posts permission)
    reviewers = WorkspaceMembership.objects.filter(
        workspace=workspace,
    ).select_related("user", "custom_role")

    for membership in reviewers:
        perms = membership.effective_permissions
        if perms.get("approve_posts", False) and membership.user != user:
            notify(
                user=membership.user,
                event_type=EventType.POST_SUBMITTED,
                title="Post submitted for review",
                body=f'{user.display_name} submitted a post for your review: "{post.caption_snippet}"',
                data={
                    "post_id": str(post.id),
                    "workspace_id": str(workspace.id),
                },
            )

    return post


def approve_post(post, user, workspace, comment=""):
    """Approve a post.

    If workspace mode is required_internal_and_client and post is pending_review,
    transitions to pending_client (not directly to approved).
    Otherwise transitions to approved.
    """
    with transaction.atomic():
        if post.status == "pending_review" and workspace.approval_workflow_mode == "required_internal_and_client":
            # Internal approval done — now needs client approval
            post.transition_to("approved")
            post.save(update_fields=["status", "updated_at"])
            # Then immediately transition to pending_client
            post.transition_to("pending_client")
            post.save(update_fields=["status", "updated_at"])

            ApprovalAction.objects.create(
                post=post,
                user=user,
                action=ApprovalAction.ActionType.APPROVED,
                comment=comment,
            )

            # Reset reminder tracking for client stage
            ApprovalReminder.objects.update_or_create(
                post=post,
                stage="pending_client",
                defaults={"reminder_count": 0, "last_reminder_at": None, "escalated": False},
            )

            # Notify client members
            _notify_clients(post, workspace)
        else:
            # Direct approval (pending_review or pending_client)
            post.transition_to("approved")
            post.save(update_fields=["status", "updated_at"])

            ApprovalAction.objects.create(
                post=post,
                user=user,
                action=ApprovalAction.ActionType.APPROVED,
                comment=comment,
            )

    # Notify post author
    if post.author and post.author != user:
        notify(
            user=post.author,
            event_type=EventType.POST_APPROVED,
            title="Post approved",
            body=f'Your post "{post.caption_snippet}" was approved by {user.display_name}.',
            data={
                "post_id": str(post.id),
                "workspace_id": str(workspace.id),
            },
        )

    return post


def request_changes(post, user, workspace, comment):
    """Request changes on a post. Comment is required."""
    if not comment.strip():
        raise ValueError("A comment is required when requesting changes.")

    with transaction.atomic():
        post.transition_to("changes_requested")
        post.save(update_fields=["status", "updated_at"])

        ApprovalAction.objects.create(
            post=post,
            user=user,
            action=ApprovalAction.ActionType.CHANGES_REQUESTED,
            comment=comment,
        )

    # Notify post author
    if post.author and post.author != user:
        notify(
            user=post.author,
            event_type=EventType.POST_CHANGES_REQUESTED,
            title="Changes requested on your post",
            body=f'{user.display_name} requested changes: "{comment[:100]}"',
            data={
                "post_id": str(post.id),
                "workspace_id": str(workspace.id),
            },
        )

    return post


def reject_post(post, user, workspace, comment):
    """Reject a post. Comment is required."""
    if not comment.strip():
        raise ValueError("A comment is required when rejecting a post.")

    with transaction.atomic():
        post.transition_to("rejected")
        post.save(update_fields=["status", "updated_at"])

        ApprovalAction.objects.create(
            post=post,
            user=user,
            action=ApprovalAction.ActionType.REJECTED,
            comment=comment,
        )

    # Notify post author
    if post.author and post.author != user:
        notify(
            user=post.author,
            event_type=EventType.POST_REJECTED,
            title="Post rejected",
            body=f'{user.display_name} rejected your post: "{comment[:100]}"',
            data={
                "post_id": str(post.id),
                "workspace_id": str(workspace.id),
            },
        )

    return post


def resubmit_post(post, user, workspace):
    """Resubmit a post after changes were requested or it was rejected."""
    with transaction.atomic():
        post.transition_to("pending_review")
        post.save(update_fields=["status", "updated_at"])

        ApprovalAction.objects.create(
            post=post,
            user=user,
            action=ApprovalAction.ActionType.RESUBMITTED,
        )

        # Reset reminder tracking
        ApprovalReminder.objects.update_or_create(
            post=post,
            stage="pending_review",
            defaults={"reminder_count": 0, "last_reminder_at": None, "escalated": False},
        )

    # Notify reviewers
    reviewers = WorkspaceMembership.objects.filter(
        workspace=workspace,
    ).select_related("user", "custom_role")

    for membership in reviewers:
        perms = membership.effective_permissions
        if perms.get("approve_posts", False) and membership.user != user:
            notify(
                user=membership.user,
                event_type=EventType.POST_SUBMITTED,
                title="Post resubmitted for review",
                body=f'{user.display_name} resubmitted a post: "{post.caption_snippet}"',
                data={
                    "post_id": str(post.id),
                    "workspace_id": str(workspace.id),
                },
            )

    return post


def bulk_approve(post_ids, user, workspace):
    """Approve multiple posts at once. Returns list of (post_id, success, error)."""
    results = []
    posts = Post.objects.filter(
        id__in=post_ids,
        workspace=workspace,
        status__in=["pending_review", "pending_client"],
    )

    for post in posts:
        try:
            approve_post(post, user, workspace)
            results.append((str(post.id), True, None))
        except ValueError as e:
            results.append((str(post.id), False, str(e)))

    return results


def bulk_reject(post_ids, user, workspace, comment):
    """Reject multiple posts with a shared comment. Returns list of (post_id, success, error)."""
    if not comment.strip():
        raise ValueError("A comment is required for bulk rejection.")

    results = []
    posts = Post.objects.filter(
        id__in=post_ids,
        workspace=workspace,
        status__in=["pending_review", "pending_client"],
    )

    for post in posts:
        try:
            reject_post(post, user, workspace, comment)
            results.append((str(post.id), True, None))
        except ValueError as e:
            results.append((str(post.id), False, str(e)))

    return results


def _notify_clients(post, workspace):
    """Send CLIENT_APPROVAL_REQUESTED notification to all client members."""
    client_memberships = WorkspaceMembership.objects.filter(
        workspace=workspace,
        workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT,
    ).select_related("user")

    for membership in client_memberships:
        notify(
            user=membership.user,
            event_type=EventType.CLIENT_APPROVAL_REQUESTED,
            title="Posts ready for your review",
            body=f"A post in {workspace.name} is waiting for your approval.",
            data={
                "post_id": str(post.id),
                "workspace_id": str(workspace.id),
            },
        )
