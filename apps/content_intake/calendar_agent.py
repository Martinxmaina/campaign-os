"""14-day calendar gap scanner."""
from __future__ import annotations
from datetime import date, timedelta
from apps.content_intake.models import ContentIntake

TARGET_CADENCE_PER_WEEK = 3

def scan_14day_gaps(workspace) -> list[dict]:
    from apps.composer.models import Post
    today = date.today()
    window_end = today + timedelta(days=14)
    scheduled_days = set(
        Post.objects.filter(
            workspace=workspace,
            scheduled_at__date__gte=today,
            scheduled_at__date__lte=window_end,
        ).values_list("scheduled_at__date", flat=True)
    )
    candidates = list(
        ContentIntake.objects.filter(
            workspace=workspace,
            status__in=["accepted", "idea"],
            sensitivity__in=["public_safe", "partner_only"],
        ).prefetch_related("unblock_conditions").order_by("-priority", "target_publish_date")[:100]
    )
    candidates = [c for c in candidates if c.is_schedulable]
    proposals = []
    used_ids = set()
    week_post_count = 0
    week_start = today
    for delta in range(14):
        day = today + timedelta(days=delta)
        if (day - week_start).days >= 7:
            week_start = day
            week_post_count = 0
        if week_post_count >= TARGET_CADENCE_PER_WEEK:
            continue
        if day in scheduled_days:
            week_post_count += 1
            continue
        candidate = next(
            (c for c in candidates if c.pk not in used_ids
             and (c.target_publish_date is None or c.target_publish_date <= day)),
            None
        )
        if candidate:
            used_ids.add(candidate.pk)
            week_post_count += 1
            proposals.append({
                "proposed_date": day.isoformat(),
                "external_id": candidate.external_id,
                "pillar_theme": candidate.pillar_theme,
                "angle": candidate.angle,
                "priority": candidate.priority,
                "channel_targets": candidate.channel_targets,
                "rationale": f"Gap on {day}, priority={candidate.priority}",
            })
    return proposals
