"""Background tasks for the publishing engine."""

import logging

from celery import shared_task

from jobs.locks import redis_lock, LockNotAcquired

logger = logging.getLogger(__name__)


@shared_task
def run_publish_cycle():
    """Poll for due posts and publish them.

    Registered as a recurring beat task (every 15s). A Redis lock
    ensures two overlapping ticks can't double-publish.
    """
    from apps.publisher.engine import PublishEngine

    try:
        with redis_lock("publish-cycle", ttl=60):
            published = PublishEngine().poll_and_publish()
            if published:
                logger.info("Publish cycle completed - %d post(s) published", published)
    except LockNotAcquired:
        logger.debug("publish cycle already running; skipping tick")
