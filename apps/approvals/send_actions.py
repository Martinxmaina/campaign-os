# apps/approvals/send_actions.py
"""One-click Send: approve + email a copy + publish (Approach A)."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from apps.composer.models import Post
from apps.composer.views import schedule_now
from apps.settings_manager.helpers import get_setting

from .models import ApprovalAction

logger = logging.getLogger(__name__)


def email_post_copy(post, to_email, reviewer):
    """Email a rendered copy of *post* to *to_email*. Returns False (no-op) when
    no address is configured; returns True after a successful send."""
    if not to_email:
        return False
    platforms = [
        pp.social_account.platform
        for pp in post.platform_posts.select_related("social_account")
    ]
    ctx = {"post": post, "reviewer": reviewer, "platforms": platforms}
    subject = f"[Sent] {post.title or post.caption_snippet}"
    text_body = render_to_string("notifications/email/post_copy.txt", ctx)
    html_body = render_to_string("notifications/email/post_copy.html", ctx)
    msg = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [to_email])
    msg.attach_alternative(html_body, "text/html")
    msg.send()
    return True


def send_for_publish(post, user):
    """Approve *post*, email a copy to the configured inbox, then publish.

    Approve mirrors the console ``approve`` branch (Post-level review_state +
    audit row + move pending_review children to approved). The email is
    best-effort (a failure is logged, never fatal). Publishing is scheduled via
    ``schedule_now`` — the gate still runs at publish time and can still block.
    """
    # 1. Approve at the Post level (matches console_views.approval_decide).
    post.review_state = Post.ReviewState.APPROVED
    post.save(update_fields=["review_state", "updated_at"])
    ApprovalAction.objects.create(
        post=post, user=user, action=ApprovalAction.ActionType.APPROVED
    )
    post.platform_posts.filter(status="pending_review").update(status="approved")

    # 2. Email a copy (best-effort; never blocks publish).
    try:
        email_post_copy(post, get_setting(post.workspace_id, "review.copy_email"), user)
    except Exception:  # noqa: BLE001 — copy email is a notification, not a gate
        logger.warning("post-copy email failed for post %s", post.id, exc_info=True)

    # 3. Publish (gate enforced downstream in publisher.engine).
    schedule_now(post)
    return post
