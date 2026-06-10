"""Intake board views."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.content_intake.models import ContentIntake, UnblockCondition


@login_required
def board(request):
    workspace = request.workspace
    if workspace is None:
        return render(request, "content_intake/board.html", {
            "items": [],
            "statuses": ContentIntake.Status.choices,
            "pillars": [],
            "status_filter": "",
            "pillar_filter": "",
        })
    qs = ContentIntake.objects.filter(workspace=workspace).exclude(
        status=ContentIntake.Status.SKIPPED
    ).prefetch_related("unblock_conditions")

    status_filter = request.GET.get("status", "")
    pillar_filter = request.GET.get("pillar", "")
    owner_filter = request.GET.get("owner", "")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if pillar_filter:
        qs = qs.filter(pillar_theme__icontains=pillar_filter)
    if owner_filter:
        qs = qs.filter(owner_raw__icontains=owner_filter)

    items = list(qs.order_by("-priority", "-created_at")[:200])
    statuses = ContentIntake.Status.choices
    pillars = (
        ContentIntake.objects.filter(workspace=workspace)
        .exclude(pillar_theme="")
        .values_list("pillar_theme", flat=True)
        .distinct()
    )
    return render(request, "content_intake/board.html", {
        "items": items,
        "statuses": statuses,
        "pillars": pillars,
        "status_filter": status_filter,
        "pillar_filter": pillar_filter,
    })


@login_required
@require_POST
def close_condition(request, condition_pk):
    condition = get_object_or_404(UnblockCondition, pk=condition_pk,
                                   intake__workspace=request.workspace)
    evidence = request.POST.get("evidence_note", "").strip()
    condition.status = UnblockCondition.ConditionStatus.CLOSED
    condition.evidence_note = evidence
    condition.closed_by = request.user
    condition.closed_at = timezone.now()
    condition.save(update_fields=["status", "evidence_note", "closed_by", "closed_at", "updated_at"])

    if request.headers.get("HX-Request"):
        return render(request, "content_intake/_condition_checklist.html", {
            "conditions": condition.intake.unblock_conditions.all(),
            "intake": condition.intake,
        })
    return HttpResponse(status=204)
