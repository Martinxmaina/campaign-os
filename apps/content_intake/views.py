"""Views for the Content Intake board (T9)."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.common.decorators import workspace_required

from .models import ContentIntake, UnblockCondition


@login_required
@workspace_required
def board(request):
    """Intake board — filterable list of ContentIntake items for the request workspace."""
    workspace = request.workspace

    qs = (
        ContentIntake.objects.filter(workspace=workspace)
        .exclude(status=ContentIntake.Status.SKIPPED)
        .prefetch_related("unblock_conditions")
        .order_by("-created_at")
    )

    status_filter = request.GET.get("status", "")
    pillar_filter = request.GET.get("pillar", "")
    owner_filter = request.GET.get("owner", "")

    if status_filter:
        qs = qs.filter(status=status_filter)
    if pillar_filter:
        qs = qs.filter(pillar_theme__icontains=pillar_filter)
    if owner_filter:
        qs = qs.filter(owner_id=owner_filter)

    status_choices = ContentIntake.Status.choices

    return render(
        request,
        "content_intake/board.html",
        {
            "workspace": workspace,
            "items": qs,
            "status_filter": status_filter,
            "pillar_filter": pillar_filter,
            "owner_filter": owner_filter,
            "status_choices": status_choices,
        },
    )


@login_required
@workspace_required
@require_POST
def close_condition(request, condition_pk):
    """Mark an UnblockCondition as closed.

    Scoped to the request workspace: the condition's intake must belong to the
    same workspace as the authenticated user's current workspace.

    HTMX: if the request carries the HX-Request header, return the
    _condition_checklist.html partial so the checklist updates in-place.
    Otherwise return a bare 204 (non-HTMX callers can reload).
    """
    workspace = request.workspace
    condition = get_object_or_404(
        UnblockCondition,
        id=condition_pk,
        intake__workspace=workspace,
    )

    evidence_note = request.POST.get("evidence_note", "").strip()

    condition.status = UnblockCondition.ConditionStatus.CLOSED
    condition.evidence_note = evidence_note
    condition.closed_by = request.user
    condition.closed_at = timezone.now()
    condition.save(update_fields=["status", "evidence_note", "closed_by", "closed_at", "updated_at"])

    if request.headers.get("HX-Request"):
        intake = condition.intake
        # Re-fetch with prefetch so the partial has the full checklist.
        intake.refresh_from_db()
        conditions = intake.unblock_conditions.order_by("created_at")
        return render(
            request,
            "content_intake/_condition_checklist.html",
            {
                "intake": intake,
                "conditions": conditions,
                "workspace": workspace,
            },
        )

    return HttpResponse(status=204)
