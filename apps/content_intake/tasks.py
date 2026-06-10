"""Celery tasks for content intake."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def sync_intake_sheet(self, workspace_id: str):
    """Sync Google Sheet intake rows for a single workspace.

    Retries up to 3 times on any exception (network / API / DB transient
    failures) with a 2-minute back-off between attempts.
    """
    from apps.content_intake.sheets_sync import sync_sheet_to_intake
    from apps.workspaces.models import Workspace

    try:
        workspace = Workspace.objects.get(pk=workspace_id)
        return sync_sheet_to_intake(workspace)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def sync_all_intake_sheets():
    """Enqueue sync_intake_sheet for every non-archived workspace.

    Only enqueues work when CONTENT_INTAKE_SHEET_ID is configured, so
    environments without Sheets credentials are a no-op.
    """
    from django.conf import settings

    from apps.workspaces.models import Workspace

    if not settings.CONTENT_INTAKE_SHEET_ID:
        return {"queued": 0}

    count = 0
    for ws in Workspace.objects.filter(is_archived=False):
        sync_intake_sheet.delay(str(ws.pk))
        count += 1
    return {"queued": count}


@shared_task
def run_calendar_gap_scan():
    """Scan all active workspaces for 14-day calendar gaps and cache proposals.

    Results are stored in the cache under the key ``calendar_proposals:<ws.pk>``
    with a 24-hour TTL.  The intake board and HERALD context builder read from
    this cache key.
    """
    from django.core.cache import cache

    from apps.content_intake.calendar_agent import scan_14day_gaps
    from apps.workspaces.models import Workspace

    results = {}
    for ws in Workspace.objects.filter(is_archived=False):
        proposals = scan_14day_gaps(ws)
        cache.set(f"calendar_proposals:{ws.pk}", proposals, timeout=86400)
        results[str(ws.pk)] = len(proposals)
    return results
