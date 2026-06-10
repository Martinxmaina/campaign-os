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
    except Workspace.DoesNotExist:
        # Workspace was deleted between enqueue and execution — nothing to do.
        logger.warning(
            "sync_intake_sheet: workspace %s no longer exists; discarding task",
            workspace_id,
        )
        return

    try:
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
    """Run the 14-day calendar gap scanner for every non-archived workspace.

    Returns a dict mapping workspace pk to the count of proposals produced
    by scan_14day_gaps. Proposals are cached for 24 hours per workspace.
    Logs a summary line per workspace.
    """
    from django.core.cache import cache

    from apps.workspaces.models import Workspace
    from apps.content_intake.calendar_agent import scan_14day_gaps

    results = {}
    for ws in Workspace.objects.filter(is_archived=False):
        proposals = scan_14day_gaps(ws)
        cache.set(f"calendar_proposals:{ws.pk}", proposals, timeout=86400)
        results[str(ws.pk)] = len(proposals)
        logger.info(
            "calendar_gap_scan: workspace=%s proposals=%d",
            ws.pk,
            len(proposals),
        )
    return results

