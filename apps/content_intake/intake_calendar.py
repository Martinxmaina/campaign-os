"""Turn an accepted intake item into a scheduled composer.Post on the calendar."""
from __future__ import annotations

from apps.composer.models import Post


def schedule_intake_item(intake, when, user):
    """Create (or reuse) a Post for this intake item, scheduled at ``when``.

    Uses the platform's native content calendar: the calendar grid renders any
    Post by its ``scheduled_at`` (apps.calendar.views.calendar_view → "posts"),
    including channel-less posts. A scheduled Post is therefore all that's
    needed — we deliberately do NOT create a separate CustomCalendarEvent
    (that layer is for campaign/launch bars; using it here would double-render
    the same item on the calendar).

    Returns the Post, or None if the item is not schedulable (blocked /
    sensitive / unverified).
    """
    if not intake.is_schedulable:
        return None

    post = intake.post
    if post is None:
        # Set scheduled_at in the INSERT itself so the create branch is a single
        # write. Only the reuse branch needs a follow-up UPDATE.
        post = Post.objects.create(
            workspace=intake.workspace,
            author=user,
            title=(intake.angle or intake.pillar_theme or intake.external_id)[:255],
            caption=intake.angle or intake.proof_point or "",
            scheduled_at=when,
        )
    else:
        post.scheduled_at = when
        post.save(update_fields=["scheduled_at", "updated_at"])

    intake.post = post
    intake.status = intake.Status.SCHEDULED
    intake.save(update_fields=["post", "status", "updated_at"])

    return post
