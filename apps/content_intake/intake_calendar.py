"""Turn an accepted intake item into a scheduled composer.Post on the calendar."""
from __future__ import annotations

import logging

from apps.composer.models import Post

logger = logging.getLogger(__name__)


def schedule_intake_item(intake, when, user):
    """Create (or reuse) a Post for this intake item, scheduled at ``when``.

    Returns the Post, or None if the item is not schedulable (blocked /
    sensitive / unverified). Also drops a CustomCalendarEvent marker so the
    item is visible on the calendar even before a channel is chosen.
    """
    if not intake.is_schedulable:
        return None

    post = intake.post
    if post is None:
        post = Post.objects.create(
            workspace=intake.workspace,
            title=(intake.angle or intake.pillar_theme or intake.external_id)[:255],
            caption=intake.angle or intake.proof_point or "",
        )

    post.scheduled_at = when
    post.save(update_fields=["scheduled_at", "updated_at"])

    intake.post = post
    intake.status = intake.Status.SCHEDULED
    intake.save(update_fields=["post", "status", "updated_at"])

    # Visible calendar marker (best-effort; never blocks scheduling).
    try:
        from apps.calendar.models import CustomCalendarEvent
        CustomCalendarEvent.objects.get_or_create(
            workspace=intake.workspace,
            title=f"📝 {post.title}"[:200],
            start_date=when.date(),
            end_date=when.date(),
            defaults={"created_by": user, "description": f"Intake {intake.external_id}"},
        )
    except Exception:
        logger.exception("calendar marker failed for intake %s", intake.external_id)

    return post
