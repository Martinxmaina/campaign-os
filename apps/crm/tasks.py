"""Ported DEAL-ENGINE Celery tasks: daily thread scoring + no-reply flagging.

These mirror the agent-service engine (``app/services/scoring.py`` +
``app/services/sequences.py::run_no_reply``) but operate on the canonical
Django CRM (``apps.crm`` is now the owner of thread data). Registered in
``jobs/schedules.py`` (the beat single source of truth).
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.crm.models import OutreachThread
from apps.crm.scoring import score_thread_features

logger = logging.getLogger(__name__)

# Thresholds (days since ``last_touch``) — parity with agent-service run_no_reply.
NO_REPLY_AMBER_DAYS = 14
NO_REPLY_RED_DAYS = 28

# Stages that are terminal — no nagging follow-ups.
CLOSED_STAGES = {OutreachThread.Stage.CONTRACTED, OutreachThread.Stage.CLOSED}

# Map thread attributes onto the 0..1 scoring features.
_WARMTH_VALUE = {"hot": 1.0, "warm": 0.6, "cold": 0.2, "": 0.2}
_SENIORITY_VALUE = {
    "c_suite": 1.0,
    "vp": 0.8,
    "director": 0.6,
    "manager": 0.4,
    "analyst": 0.2,
    "": 0.3,
}


def _recency_value(thread, now) -> float:
    """0..1 recency: touched today → 1.0, decays to 0 by ~60 days."""
    if not thread.last_touch:
        return 0.0
    age_days = max(0, (now - thread.last_touch).days)
    return max(0.0, 1.0 - age_days / 60.0)


def _features_for(thread, now) -> dict:
    """Assemble the scoring feature vector from a Django thread."""
    warmth = _WARMTH_VALUE.get((thread.warmth or "").lower(), 0.2)
    seniority = _SENIORITY_VALUE.get("", 0.3)
    contact = thread.primary_contact
    if contact is not None:
        seniority = _SENIORITY_VALUE.get((contact.seniority or "").lower(), 0.3)
    recency = _recency_value(thread, now)
    track_alignment = 1.0 if thread.track else 0.0
    pillar_fit = 1.0 if thread.pillar else 0.0
    return {
        "warmth": warmth,
        "seniority_org_fit": seniority,
        "pillar_fit": pillar_fit,
        "engagement_recency": recency,
        "engagement_frequency": recency,  # proxy until per-activity counts land
        "track_alignment": track_alignment,
    }


def _traffic_for_quintile(quintile: int) -> str:
    if quintile >= 4:
        return "green"
    if quintile >= 2:
        return "amber"
    return "red"


@shared_task(name="apps.crm.tasks.score_all_threads")
def score_all_threads() -> dict:
    """Recompute score/quintile/traffic_light for every non-closed thread."""
    now = timezone.now()
    scored = 0
    qs = OutreachThread.objects.exclude(stage__in=CLOSED_STAGES).select_related(
        "primary_contact"
    )
    for thread in qs:
        score, quintile, _action = score_thread_features(_features_for(thread, now))
        thread.score = score
        thread.quintile = quintile
        thread.traffic_light = _traffic_for_quintile(quintile)
        thread.save(update_fields=["score", "quintile", "traffic_light", "updated_at"])
        scored += 1
    logger.info("crm.score_all_threads scored=%s", scored)
    return {"scored": scored}


@shared_task(name="apps.crm.tasks.flag_no_reply")
def flag_no_reply() -> dict:
    """Flip traffic_light amber (>14d) / red (>28d) on stale, open threads.

    Skips closed/contracted stages and threads with no ``last_touch``.
    """
    now = timezone.now()
    amber = 0
    red = 0
    qs = OutreachThread.objects.exclude(stage__in=CLOSED_STAGES).filter(
        last_touch__isnull=False
    )
    for thread in qs:
        age = (now - thread.last_touch).days
        if age >= NO_REPLY_RED_DAYS and thread.traffic_light != "red":
            thread.traffic_light = "red"
            if not thread.next_action:
                thread.next_action = "Owner: send gate-checked follow-up (no reply 28d+)"
            thread.save(update_fields=["traffic_light", "next_action", "updated_at"])
            red += 1
        elif NO_REPLY_AMBER_DAYS <= age < NO_REPLY_RED_DAYS and thread.traffic_light == "green":
            thread.traffic_light = "amber"
            if not thread.next_action:
                thread.next_action = "Owner: send gate-checked follow-up (no reply 14d+)"
            thread.save(update_fields=["traffic_light", "next_action", "updated_at"])
            amber += 1
    logger.info("crm.flag_no_reply amber=%s red=%s", amber, red)
    return {"amber": amber, "red": red}


@shared_task
def mirror_crm_tracker() -> dict:
    """Daily: mirror the live CRM pipeline into the configured Google Sheet tab.

    No-ops cleanly when CRM_TRACKER_SHEET_ID is unset or the Google token lacks the
    read-write ``spreadsheets`` scope (a re-consent is required to write)."""
    from apps.crm.sheet_mirror import mirror_pipeline_to_sheet

    result = mirror_pipeline_to_sheet()
    logger.info("crm.mirror_crm_tracker %s", result)
    return result
