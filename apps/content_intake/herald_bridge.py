# apps/content_intake/herald_bridge.py
"""Bridge: push an accepted ContentIntake item to HERALD for drafting.

Django calls the agent-service's existing POST /agents/herald/draft with the
intake item rendered as the `brief`. No new storage on agent-service.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.common.agent_client import agent_post
from apps.content_intake.models import ContentIntake
from apps.content_intake.sector_map import map_pillar_to_sector

logger = logging.getLogger(__name__)

_AGENT_VISIBLE = frozenset(["public_safe", "partner_only"])


def build_brief(intake: ContentIntake) -> str:
    """Render an intake item into a HERALD brief string."""
    parts = [intake.angle.strip()] if intake.angle else []
    if intake.proof_point:
        parts.append(f"Proof: {intake.proof_point.strip()}")
    if intake.target_audience:
        parts.append(f"Audience: {intake.target_audience.strip()}")
    if intake.channel_targets:
        chans = ", ".join(
            t.get("platform", "") for t in intake.channel_targets if t.get("platform")
        )
        if chans:
            parts.append(f"Channels: {chans}")
    if intake.reference_links:
        srcs = []
        for l in intake.reference_links:
            if isinstance(l, dict) and l.get("url"):
                srcs.append(f"{l.get('title') or l['url']} ({l['url']})")
            elif isinstance(l, str):  # tolerate legacy bare-string links
                srcs.append(l)
        if srcs:
            parts.append("Sources: " + "; ".join(srcs))
    return ". ".join(p for p in parts if p)


def _is_eligible(intake: ContentIntake) -> bool:
    if intake.status != ContentIntake.Status.ACCEPTED:
        return False
    if intake.sensitivity not in _AGENT_VISIBLE:
        return False
    if intake.herald_drafted_at is not None:
        return False
    if not intake.is_schedulable:
        return False
    return True


def request_herald_draft(intake: ContentIntake) -> bool:
    """Ask HERALD to draft this intake item. Returns True on success.

    Idempotent: items already drafted (herald_drafted_at set) are skipped.
    Failure leaves the item unchanged so the next sync retries.
    """
    if not _is_eligible(intake):
        return False

    sector = map_pillar_to_sector(intake.pillar_theme)
    brief = build_brief(intake)

    is_joseph = (intake.owner_raw or "").strip().lower().startswith("joseph") or any(
        (t.get("account") or "").lower() == "joseph" for t in (intake.channel_targets or [])
    )
    payload = {"sector": sector, "brief": brief, "count": 1}
    if is_joseph:
        payload["voice_user"] = "joseph"

    try:
        result = agent_post("/agents/herald/draft", payload)
    except Exception:
        logger.exception("HERALD draft request failed for intake=%s", intake.external_id)
        return False

    content_id = ""
    proposals = result.get("proposals") if isinstance(result, dict) else None
    if proposals and isinstance(proposals, list) and isinstance(proposals[0], dict):
        content_id = str(proposals[0].get("content_id", ""))

    intake.herald_content_id = content_id
    intake.herald_drafted_at = timezone.now()
    intake.status = ContentIntake.Status.DRAFTING
    intake.save(update_fields=["herald_content_id", "herald_drafted_at", "status", "updated_at"])
    return True
