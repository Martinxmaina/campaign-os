"""Celery tasks for the outreach engine.

``advance_sequences`` is the daily beat (registered as ``outreach-advance`` in
``jobs/schedules.py``) that drives :func:`apps.outreach.sequences.advance` —
gating + sending due email steps and opening owner tasks for due human-channel
steps. ``run_no_reply_followups`` (``outreach-no-reply``) drives
:func:`apps.outreach.triage.run_no_reply` — drafting follow-ups for unanswered
sent steps. Network (gate + Gmail) lives behind ``send_email``; nothing heavy is
imported at module load.
"""
from __future__ import annotations

import logging

from celery import shared_task

from apps.outreach.sequences import advance
from apps.outreach.triage import run_no_reply

logger = logging.getLogger(__name__)


@shared_task(name="apps.outreach.tasks.advance_sequences")
def advance_sequences() -> dict:
    """Daily sweep: resolve all due sequence steps. Returns ``{sent, tasks}``."""
    result = advance()
    logger.info("outreach.advance_sequences %s", result)
    return result


@shared_task(name="apps.outreach.tasks.run_no_reply_followups")
def run_no_reply_followups() -> dict:
    """Daily sweep: draft follow-ups for unanswered sends. Returns ``{amber, red}``."""
    result = run_no_reply()
    logger.info("outreach.run_no_reply_followups %s", result)
    return result
