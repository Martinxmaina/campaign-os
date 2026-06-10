"""Background tasks for organization lifecycle."""

import logging

from celery import shared_task
from django.utils import timezone

from .models import Organization

logger = logging.getLogger(__name__)


@shared_task
def execute_scheduled_org_deletion(org_id):
    """Delete an org whose 14-day grace period has elapsed.

    Idempotent and cancellation-safe: re-reads the current state and bails
    out if the org is already gone, the user cancelled deletion, or the
    scheduled datetime is still in the future.
    """
    try:
        org = Organization.objects.get(pk=org_id)
    except Organization.DoesNotExist:
        logger.info("org %s already gone, nothing to purge", org_id)
        return

    if not org.deletion_requested_at or not org.deletion_scheduled_for:
        logger.info("org %s has no pending deletion; user must have cancelled", org_id)
        return

    if org.deletion_scheduled_for > timezone.now():
        logger.info("org %s scheduled_for is in the future; skipping this run", org_id)
        return

    org_name = org.name
    org.hard_delete()
    logger.info('org "%s" (%s) purged after grace period', org_name, org_id)


@shared_task
def sweep_scheduled_org_deletions():
    """Daily durability sweep: purge every org whose deletion eta has passed.

    This is the durability net required because the eta-enqueued Celery
    message lives only in Redis — a broker restart without persistence,
    eviction, or a broker flush during cutover would silently strand the
    org in 'pending deletion' forever.  This task is registered in
    BEAT_SCHEDULE (daily) and re-uses the already-idempotent
    execute_scheduled_org_deletion body, so every guard (cancelled,
    future, already-gone) is preserved.

    The sweep also eliminates the long-eta / Redis visibility-timeout
    redelivery loop: with CELERY_TASK_ACKS_LATE=True and the default
    Redis visibility timeout of 1 h, an unacked 14-day eta message is
    restored and re-fetched roughly hourly for the entire grace window
    (~300 redundant in-memory deliveries).  With the sweep in place the
    eta enqueue is optional insurance; the beat job is the source of
    truth for firing the deletion.
    """
    now = timezone.now()
    due = Organization.objects.filter(
        deletion_requested_at__isnull=False,
        deletion_scheduled_for__lte=now,
    )
    count = 0
    for org in due:
        org_name = org.name
        org_id = org.pk
        org.hard_delete()
        logger.info('sweep: org "%s" (%s) purged after grace period', org_name, org_id)
        count += 1
    if count:
        logger.info("sweep_scheduled_org_deletions: purged %d org(s)", count)
    else:
        logger.debug("sweep_scheduled_org_deletions: no orgs due for deletion")
