"""Intake board views."""
import uuid
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.content_intake.draft_post import ensure_draft_post
from apps.content_intake.herald_bridge import request_herald_draft
from apps.content_intake.models import ContentIntake, UnblockCondition
from apps.content_intake.progress import content_pipeline_progress
from apps.content_intake.sheets_sync import sync_sheet_to_intake


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
            "sort": "",
            "pipeline_progress": content_pipeline_progress(None),
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

    # Ascending-only: the table headers emit bare ?sort=<col> links with no
    # asc/desc toggle, so no descending ("-pillar", etc.) variant is ever
    # requested. Keep this map in lockstep with the header links in _table.html.
    _SORT_MAP = {
        "pillar": "pillar_theme",
        "status": "status",
        "priority": "-priority",
        "owner": "owner_raw",
        "created": "created_at",
    }
    sort = request.GET.get("sort", "")
    order = _SORT_MAP.get(sort, "-priority")
    items = list(qs.order_by(order, "-created_at")[:200])
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
    ctx = {
        "items": items,
        "statuses": statuses,
        "pillars": pillars,
        "status_filter": status_filter,
        "pillar_filter": pillar_filter,
        "sort": sort,
        "last_sync_at": activity["last_sync_at"],
        "last_draft_at": activity["last_draft_at"],
        # Union of created (Posts) + curated (intake) content, de-duped and
        # mapped onto one funnel — drives the progress strip on both board views.
        "pipeline_progress": content_pipeline_progress(workspace),
    }
    if request.GET.get("view") == "board":
        lanes = {"todo": [], "in_progress": [], "done": []}
        for it in items:
            lanes[it.board_stage].append(it)
        ordered = [("todo", "To Do"), ("in_progress", "In Progress"), ("done", "Done")]
        ctx_board = {**ctx, "lanes_labels": ordered,
                     "lane_todo": lanes["todo"], "lane_in_progress": lanes["in_progress"],
                     "lane_done": lanes["done"], "view": "board"}
        return render(request, "content_intake/board_kanban.html", ctx_board)
    if request.GET.get("partial"):
        return render(request, "content_intake/_table.html", ctx)
    return render(request, "content_intake/board.html", ctx)


@login_required
@require_POST
def sync_now(request):
    """Force an immediate sheet pull, then return the refreshed table partial."""
    if request.workspace is not None:
        try:
            sync_sheet_to_intake(request.workspace)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("manual sync_now failed")
    # Re-run the board query path in partial mode by delegating to board().
    request.GET = request.GET.copy()
    request.GET["partial"] = "1"
    return board(request)


@login_required
@require_POST
def move_stage(request, intake_pk):
    """Transition an intake item between Kanban lanes (todo|in_progress|done).

    Pure stage change — NEVER drafts. HERALD only runs via the explicit manual
    "Draft with HERALD" action (draft_now).

    State-integrity rules:
    - todo  → status ACCEPTED   (only if the item is not already terminal)
    - in_progress → status DRAFTING (only if the item is not already terminal)
    - done  → status APPROVED   (only if is_schedulable; blocked/sensitive = no-op)
    A "terminal" item is one whose status is in ContentIntake._BOARD_DONE
    (scheduled/published/archived). Such items are NEVER silently demoted back to
    accepted/drafting by a lane drag — that would revert a published/scheduled
    item. Re-opening a terminal item is a separate explicit action, not this view.

    NOT-YET-WIRED: no UI currently posts here (the board is a table, not a
    drag/drop Kanban). See config/console_urls.py for the wiring TODO.
    """
    if request.workspace is None:
        return HttpResponse(status=403)
    item = get_object_or_404(ContentIntake, pk=intake_pk, workspace=request.workspace)
    to_stage = request.POST.get("to_stage", "")

    # Terminal-state guard: an item already in the "done" lane is
    # scheduled/published/archived (ContentIntake._BOARD_DONE). Dragging it back
    # to "todo" or "in_progress" must NOT silently revert a published/scheduled
    # item to accepted/drafting — those demotions are a no-op here. Re-opening a
    # terminal item is an explicit action handled elsewhere, not a Kanban drag.
    is_terminal = item.status in ContentIntake._BOARD_DONE

    if to_stage == "in_progress" and not is_terminal:
        item.status = ContentIntake.Status.DRAFTING
        item.save(update_fields=["status", "updated_at"])
    elif to_stage == "todo" and not is_terminal:
        item.status = ContentIntake.Status.ACCEPTED
        item.save(update_fields=["status", "updated_at"])
    elif to_stage == "done" and item.is_schedulable and not is_terminal:
        # Mark approved; actual scheduling happens via the add-to-calendar picker.
        # `not is_terminal`: a scheduled/published/archived item is already past
        # "done" — re-asserting APPROVED would silently DEMOTE it (e.g. published →
        # approved). is_schedulable alone does not exclude terminal items, so the
        # explicit terminal guard is required here just as on the other branches.
        item.status = ContentIntake.Status.APPROVED
        item.save(update_fields=["status", "updated_at"])
    # No-ops (card stays put): blocked/sensitive → done; and any demote of a
    # terminal (scheduled/published/archived) item back to todo/in_progress.

    request.GET = request.GET.copy()
    request.GET["view"] = "board"
    return board(request)


@login_required
def row_panel(request, intake_pk):
    item = None
    if request.workspace is not None:
        item = get_object_or_404(
            ContentIntake.objects.prefetch_related("unblock_conditions"),
            pk=intake_pk, workspace=request.workspace,
        )
    return render(request, "content_intake/_panel.html", {"item": item})


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
def add_to_calendar(request):
    """Schedule one or many selected intake items. Returns the table partial."""
    from datetime import datetime
    from django.db.models import Count, Q
    from django.utils import timezone as _tz
    from apps.content_intake.intake_calendar import schedule_intake_item

    ids = request.POST.getlist("ids")
    raw_when = request.POST.get("scheduled_at", "").strip()
    when = None
    if raw_when:
        try:
            parsed = datetime.fromisoformat(raw_when)
            when = parsed if parsed.tzinfo else _tz.make_aware(parsed)
        except ValueError:
            when = None
    if when is None:
        when = _tz.now()

    if request.workspace is not None:
        # Bulk hot path: schedule_intake_item -> is_schedulable ->
        # has_open_conditions. That property reads an ``open_cond_count``
        # annotation when present and otherwise falls back to a per-instance
        # EXISTS query (one per selected item -> O(N)). The model docstring
        # prescribes prefetch+annotate for list contexts, so annotate the open
        # condition count (kills the per-item EXISTS) and prefetch the related
        # set (kills the per-item fetch when the calendar marker / templates read
        # ``unblock_conditions.all()``). Together this keeps the loop O(1) in
        # condition queries regardless of how many items are scheduled.
        items = (
            ContentIntake.objects.filter(pk__in=ids, workspace=request.workspace)
            .annotate(open_cond_count=Count(
                "unblock_conditions",
                filter=Q(unblock_conditions__status=UnblockCondition.ConditionStatus.OPEN),
            ))
            .prefetch_related("unblock_conditions")
        )
        for item in items:
            schedule_intake_item(item, when, request.user)

    request.GET = request.GET.copy()
    request.GET["partial"] = "1"
    return board(request)


@login_required
@require_POST
def draft_selected(request):
    """Draft every eligible selected intake item with HERALD. Returns table partial."""
    from django.db.models import Count, Q

    ids = request.POST.getlist("ids")
    if request.workspace is not None:
        # Bulk hot path: request_herald_draft -> _is_eligible -> is_schedulable
        # -> has_open_conditions. That property reads an ``open_cond_count``
        # annotation when present and otherwise falls back to a per-instance
        # EXISTS query (one per selected item -> O(N)). The model docstring
        # prescribes prefetch+annotate for list contexts, so annotate the open
        # condition count (kills the per-item EXISTS) and prefetch the related
        # set (kills the per-item fetch when build_brief / templates read
        # ``unblock_conditions.all()``). Mirrors the add_to_calendar fix to keep
        # the loop O(1) in condition queries regardless of selection size.
        items = (
            ContentIntake.objects.filter(pk__in=ids, workspace=request.workspace)
            .annotate(open_cond_count=Count(
                "unblock_conditions",
                filter=Q(unblock_conditions__status=UnblockCondition.ConditionStatus.OPEN),
            ))
            .prefetch_related("unblock_conditions")
        )
        for item in items:
            try:
                request_herald_draft(item)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("bulk draft failed for %s", item.external_id)
    request.GET = request.GET.copy()
    request.GET["partial"] = "1"
    return board(request)


@login_required
@require_POST
def draft_now(request, intake_pk):
    """Manually ask HERALD to draft a single intake item."""
    if request.workspace is None:
        raise PermissionDenied("No workspace context resolved for this request.")

    intake = get_object_or_404(ContentIntake, pk=intake_pk, workspace=request.workspace)
    ok = request_herald_draft(intake)
    if ok:
        ensure_draft_post(intake)
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


@login_required
@require_POST
def draft_now_panel(request, intake_pk):
    """Manually ask HERALD to draft a single intake item, from the board panel.

    The board's detail panel (``_panel.html``) lives in a ``#intake-panel`` slot
    that is the swap target for row clicks. The legacy ``draft_now`` view re-renders
    ``_card.html`` (a ``#intake-card-{pk}`` div) and, on failure, retargets to
    ``#intake-card-{pk}`` — neither of which exists on the table-based board. Swapping
    a card fragment into ``#intake-panel`` would destroy the ``#intake-panel`` id and
    break every subsequent row click, and the failure retarget would silently drop the
    error banner. This panel-aware variant re-renders ``_panel.html`` in place so the
    ``#intake-panel`` id is preserved on success and the error banner is surfaced inside
    the panel on failure.
    """
    if request.workspace is None:
        raise PermissionDenied("No workspace context resolved for this request.")

    intake = get_object_or_404(
        ContentIntake.objects.prefetch_related("unblock_conditions"),
        pk=intake_pk, workspace=request.workspace,
    )
    ok = request_herald_draft(intake)
    if ok:
        ensure_draft_post(intake)
    if request.headers.get("HX-Request"):
        if ok:
            # Success: re-render the panel so the button hides and status flips to
            # "drafting" (request_herald_draft mutated the item in place). The
            # outer #intake-panel id is preserved for subsequent row clicks.
            return render(request, "content_intake/_panel.html", {"item": intake})
        # Failure: surface a visible error banner. Stock HTMX will not swap a
        # non-2xx body, so return 200 and prepend the banner into the panel via
        # HX-Reswap (the #intake-panel id is left intact). Signal observers via
        # the HX-Trigger error event. The non-HX branch below uses 409.
        response = render(request, "content_intake/_draft_error.html")
        response["HX-Retarget"] = "#intake-panel"
        response["HX-Reswap"] = "afterbegin"
        response["HX-Trigger"] = "heraldDraftFailed"
        return response
    return HttpResponse(status=204 if ok else 409)


# Priority choices offered in the manual-intake form (value, label). Kept in
# lockstep with ContentIntake.Priority so the select never emits a value the
# model would reject.
_MANUAL_PRIORITY_CHOICES = ContentIntake.Priority.choices


@login_required
def manual_intake(request, workspace_id):
    """Manually add a single content item to the intake register.

    GET  → render the form. POST → create a ContentIntake and redirect back to
    the Content Studio board (``console:content``). Intake is otherwise
    Google-Sheets-sync-only; this is the human "＋ Add content" front door.

    Workspace access is enforced via the shared composer guard
    (login + membership; raises PermissionDenied on a non-member), matching the
    contract every AI-studio surface uses.
    """
    # Reuse the canonical membership/403 guard so this surface behaves exactly
    # like the workspace-scoped composer views (login_required + membership).
    from apps.composer.views import _get_workspace

    workspace = _get_workspace(request, workspace_id)

    # Where we send the user after a successful create. console:content is the
    # Content Studio board this button lives on; fall back to the intake board
    # if the console route is unavailable for any reason.
    try:
        success_url = reverse("console:content")
    except NoReverseMatch:  # pragma: no cover - defensive
        try:
            success_url = reverse("console:intake-board")
        except NoReverseMatch:  # pragma: no cover
            success_url = "/"

    if request.method == "POST":
        pillar_theme = (request.POST.get("pillar_theme") or "").strip()
        angle = (request.POST.get("angle") or "").strip()
        proof_point = (request.POST.get("proof_point") or "").strip()
        target_audience = (request.POST.get("target_audience") or "").strip()
        priority = (request.POST.get("priority") or ContentIntake.Priority.MEDIUM).strip()
        raw_date = (request.POST.get("target_publish_date") or "").strip()

        # Validation: pillar/theme is the one hard-required field (an intake row
        # with no theme is meaningless). Everything else is optional and must
        # never 500 on a blank value.
        errors = {}
        if not pillar_theme:
            errors["pillar_theme"] = "Pillar / theme is required."
        if priority not in ContentIntake.Priority.values:
            priority = ContentIntake.Priority.MEDIUM

        target_publish_date = None
        if raw_date:
            try:
                target_publish_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                errors["target_publish_date"] = "Use a valid date (YYYY-MM-DD)."

        if errors:
            return render(
                request,
                "content_intake/manual_intake.html",
                {
                    "workspace": workspace,
                    "errors": errors,
                    "priority_choices": _MANUAL_PRIORITY_CHOICES,
                    # Echo back what the user typed so nothing is lost on re-render.
                    "form": {
                        "pillar_theme": pillar_theme,
                        "angle": angle,
                        "proof_point": proof_point,
                        "target_audience": target_audience,
                        "priority": priority,
                        "target_publish_date": raw_date,
                    },
                },
                status=400,
            )

        ContentIntake.objects.create(
            workspace=workspace,
            external_id=f"manual-{uuid.uuid4()}",
            pillar_theme=pillar_theme,
            angle=angle,
            proof_point=proof_point,
            target_audience=target_audience,
            priority=priority,
            status=ContentIntake.Status.IDEA,
            sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
            proof_status=ContentIntake.ProofStatus.TBD,
            target_publish_date=target_publish_date,
            submitted_by=request.user,
            owner=request.user,
        )
        return redirect(success_url)

    # GET — blank form.
    return render(
        request,
        "content_intake/manual_intake.html",
        {
            "workspace": workspace,
            "errors": {},
            "priority_choices": _MANUAL_PRIORITY_CHOICES,
            "form": {
                "pillar_theme": "",
                "angle": "",
                "proof_point": "",
                "target_audience": "",
                "priority": ContentIntake.Priority.MEDIUM,
                "target_publish_date": "",
            },
        },
    )
