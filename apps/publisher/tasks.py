"""Background tasks for the publishing engine."""

import logging

from celery import shared_task

from jobs.locks import redis_lock, LockNotAcquired

# Imported at module level so the reconcile task's collaborators can be patched
# at ``apps.publisher.tasks.get_provider`` / ``...._resolve_publish_credentials``.
from apps.publisher.engine import _resolve_publish_credentials  # noqa: E402
from providers import get_provider  # noqa: E402

logger = logging.getLogger(__name__)


@shared_task
def run_publish_cycle():
    """Poll for due posts and publish them.

    Registered as a recurring beat task (every 15s).  A token-checked Redis
    lock (TTL=600s, covering the 540s soft time limit) ensures two overlapping
    ticks cannot double-publish: the lock uses a UUID value and a Lua
    compare-and-delete on release, so a slow cycle's finally-block cannot evict
    a newer holder's lock after a TTL expiry.
    """
    from apps.publisher.engine import PublishEngine

    try:
        with redis_lock("publish-cycle", ttl=600):
            published = PublishEngine().poll_and_publish()
            if published:
                logger.info("Publish cycle completed - %d post(s) published", published)
    except LockNotAcquired:
        logger.debug("publish cycle already running; skipping tick")


@shared_task
def reconcile_blotato_posts():
    """Finalize Blotato posts parked at 'publishing' by polling their status.

    Idempotent and never re-submits — it only reads GET /posts/{id} and moves
    the PlatformPost to published/failed once Blotato reports a terminal state.
    """
    from django.utils import timezone

    from apps.composer.models import PlatformPost

    qs = PlatformPost.objects.filter(
        status=PlatformPost.Status.PUBLISHING,
        social_account__platform__startswith="blotato_",
    ).exclude(platform_post_id="").select_related("social_account__workspace__organization")

    for pp in qs:
        try:
            creds = _resolve_publish_credentials(pp.social_account)
            provider = get_provider(pp.social_account.platform, creds)
            data = provider.check_status(pp.platform_post_id)
        except Exception:  # noqa: BLE001 - one bad row must not stall the sweep
            logging.getLogger(__name__).warning(
                "blotato reconcile failed for %s", pp.id, exc_info=True)
            continue
        status = (data.get("status") or "").lower()
        if status == "published":
            pp.status = PlatformPost.Status.PUBLISHED
            pp.published_at = timezone.now()
            pp.publish_error = ""
            pp.save(update_fields=["status", "published_at", "publish_error", "updated_at"])
        elif status == "failed":
            pp.status = PlatformPost.Status.FAILED
            pp.publish_error = data.get("errorMessage") or "Blotato publish failed"
            pp.save(update_fields=["status", "publish_error", "updated_at"])
        # else still in-progress → leave for the next sweep
