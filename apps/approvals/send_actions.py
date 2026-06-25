# apps/approvals/send_actions.py
"""One-click Send: approve + email a copy + publish (Approach A)."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

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
