"""Build intake context dict for HERALD/ATLAS deliberation."""
from __future__ import annotations

from django.db.models import Prefetch

from apps.content_intake.models import ContentIntake, UnblockCondition
from apps.content_intake.sector_map import map_pillar_to_sector

_PRIORITY_WEIGHTS = {"H": 3, "M": 2, "L": 1}
_AGENT_VISIBLE_SENSITIVITIES = frozenset([
    ContentIntake.Sensitivity.PUBLIC_SAFE,
    ContentIntake.Sensitivity.PARTNER_ONLY,
])
_DRAFTABLE_STATUSES = frozenset([
    ContentIntake.Status.IDEA,
    ContentIntake.Status.ACCEPTED,
    ContentIntake.Status.DRAFTING,
])


def build_intake_context(workspace) -> dict:
    """Return serialisable context dict for agent prompts.

    Excludes private_hold/confidential — agents must NOT see those.
    Submitted items get priority_weight boost.

    Query strategy: a single filtered Prefetch fetches only OPEN conditions so
    no in-Python status filter is needed in the loop.
    """
    _open_conditions_prefetch = Prefetch(
        "unblock_conditions",
        queryset=UnblockCondition.objects.filter(
            status=UnblockCondition.ConditionStatus.OPEN
        ),
        to_attr="open_unblock_conditions",
    )
    qs = (
        ContentIntake.objects.filter(
            workspace=workspace,
            sensitivity__in=_AGENT_VISIBLE_SENSITIVITIES,
            status__in=_DRAFTABLE_STATUSES,
        )
        .prefetch_related(_open_conditions_prefetch)
        .order_by("-priority", "-created_at")[:50]
    )
    items = []
    for intake in qs:
        open_conditions = [
            {"type": c.condition_type, "description": c.description}
            for c in intake.open_unblock_conditions
        ]
        items.append({
            "external_id": intake.external_id,
            "pillar_theme": intake.pillar_theme,
            "sector": map_pillar_to_sector(intake.pillar_theme),
            "angle": intake.angle,
            "proof_point": intake.proof_point,
            "target_audience": intake.target_audience,
            "channel_targets": intake.channel_targets,
            "sensitivity": intake.sensitivity,
            "priority": intake.priority,
            "priority_weight": _PRIORITY_WEIGHTS.get(intake.priority, 2),
            "target_publish_date": intake.target_publish_date.isoformat() if intake.target_publish_date else None,
            "is_schedulable": intake.is_schedulable,
            "open_conditions": open_conditions,
            "notes": intake.notes_raw,
        })
    return {"intake_items": items, "total_visible": len(items), "workspace": str(workspace.pk)}
