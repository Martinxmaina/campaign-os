"""Intake board views."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.content_intake.herald_bridge import request_herald_draft
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
        if status_filter not in ContentIntake.Status.values:
            status_filter = ""
        else:
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
    # Activity badge timestamps: most-recent sheet sync and HERALD draft across
    # this workspace's intake items. Computed unfiltered so the badge reflects
    # workspace-wide activity, not the currently filtered subset.
    activity = ContentIntake.objects.filter(workspace=workspace).aggregate(
        last_sync_at=Max("last_synced_at"),
        last_draft_at=Max("herald_drafted_at"),
    )
    return render(request, "content_intake/board.html", {
        "items": items,
        "statuses": statuses,
        "pillars": pillars,
        "status_filter": status_filter,
        "pillar_filter": pillar_filter,
        "last_sync_at": activity["last_sync_at"],
        "last_draft_at": activity["last_draft_at"],
    })


@login_required
@require_POST
def close_condition(request, condition_pk):
    # Guard: workspace must be resolved by RBAC middleware before proceeding.
    # Without this check, a misconfigured middleware (no last_workspace_id, no
    # workspace URL kwarg) would silently return 404 instead of 403, masking
    # the misconfiguration.
    if request.workspace is None:
        raise PermissionDenied("No workspace context resolved for this request.")

    condition = get_object_or_404(UnblockCondition, pk=condition_pk,
                                   intake__workspace=request.workspace)
    evidence = request.POST.get("evidence_note", "").strip()
    condition.status = UnblockCondition.ConditionStatus.CLOSED
    condition.evidence_note = evidence
    condition.closed_by = request.user
    condition.closed_at = timezone.now()
    condition.save(update_fields=["status", "evidence_note", "closed_by", "closed_at", "updated_at"])

    if request.headers.get("HX-Request"):
        # Prefetch unblock_conditions to avoid an N+1 query when the checklist
        # partial renders condition.intake.unblock_conditions.all().
        intake = (
            ContentIntake.objects.prefetch_related("unblock_conditions")
            .get(pk=condition.intake_id)
        )
        return render(request, "content_intake/_condition_checklist.html", {
            "conditions": intake.unblock_conditions.all(),
            "intake": intake,
        })
    return HttpResponse(status=204)


@login_required
@require_POST
def draft_now(request, intake_pk):
    """Manually ask HERALD to draft a single intake item."""
    if request.workspace is None:
        raise PermissionDenied("No workspace context resolved for this request.")

    intake = get_object_or_404(ContentIntake, pk=intake_pk, workspace=request.workspace)
    ok = request_herald_draft(intake)
    if request.headers.get("HX-Request"):
        if ok:
            # Success: re-render the card so the button hides and status flips
            # to "drafting" (request_herald_draft mutated the item in place).
            return render(request, "content_intake/_card.html", {"item": intake})
        # Failure: prepend a visible error banner into the card instead of
        # silently re-rendering the unchanged card as a 200 no-op. Retarget the
        # swap so the button stays put and the user gets actionable feedback.
        #
        # Stock HTMX (no response-targets extension is loaded) will NOT swap a
        # non-2xx body, so a raw 409 would be dropped and the user would see
        # nothing. We therefore return 200 so the banner renders, and signal the
        # failure to clients/observers via the HX-Trigger error event. The
        # non-HX branch below still uses 409 for API-style callers.
        response = render(request, "content_intake/_draft_error.html")
        response["HX-Retarget"] = f"#intake-card-{intake.pk}"
        response["HX-Reswap"] = "afterbegin"
        response["HX-Trigger"] = "heraldDraftFailed"
        return response
    return HttpResponse(status=204 if ok else 409)
