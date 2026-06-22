"""Team thread CRUD — edit / log activity / add task on an ``OutreachThread``.

The CRM is canonical in Django (the first strangler step), so a thread is a local
``apps.crm.OutreachThread`` row. The team operates on it here:

  POST /crm/threads/<id>/edit/      → ``thread_edit``     : stage / owner / next_action
  POST /crm/threads/<id>/activity/  → ``thread_activity`` : append an Activity (append-only)
  POST /crm/threads/<id>/task/      → ``thread_task``     : create a Task

Every view is gated by ``_can_manage_crm`` (staff or an owner/admin/campaign_owner
workspace role), reused from the import wizard. These are pure Django writes — the
dossier is the only thing fetched from agent-service (by id, elsewhere). The
``_activity_timeline``/``_task_list`` partials render an HTMX swap-back of the
fresh log so the Joseph drawer's Timeline/Tasks tabs update in place. CSP-safe.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.crm.models import Activity, OutreachThread, Task
from apps.crm.views_import import _can_manage_crm
from apps.joseph import readers


def _activities(thread):
    """Append-only Activity log for a thread (newest first via Meta.ordering)."""
    return thread.activities.select_related("actor").all()


def _tasks(thread):
    """Open-then-rest Task list for a thread (open first, newest first)."""
    return thread.tasks.select_related("owner").order_by("status", "-created_at")


@login_required
def pipeline(request):
    """Team **deal** pipeline — every owner's CRM threads, bucketed into stage
    columns with an Owner badge + owner/track filter chips. This is the relocated
    home of the deal board (it used to sit under the content console's "Team
    pipeline"); deals now live with the rest of the CRM. Drag-to-restage posts to
    the shared ``crm:thread-set-stage`` endpoint. Empty DB → empty columns, never
    a 500.
    """
    from apps.joseph.views import _build_pipeline_columns, _crm_thread_card, _crm_threads

    if not _can_manage_crm(request):
        return HttpResponseForbidden("The pipeline is not available for your role.")

    owner_filter = (request.GET.get("owner") or "").strip()
    track_filter = (request.GET.get("track") or "").strip()

    all_threads = list(_crm_threads())  # unfiltered — drives the chip lists.

    seen, owner_chips = set(), []
    for t in all_threads:
        if t.owner_id and t.owner_id not in seen:
            seen.add(t.owner_id)
            owner_chips.append({
                "id": str(t.owner_id),
                "name": (t.owner.name or t.owner.email) if t.owner_id else "",
            })
    owner_chips.sort(key=lambda c: c["name"].lower())
    track_chips = sorted({t.track for t in all_threads if t.track})

    visible = all_threads
    if owner_filter:
        visible = [t for t in visible if str(t.owner_id or "") == owner_filter]
    if track_filter:
        visible = [t for t in visible if t.track == track_filter]

    columns = _build_pipeline_columns([_crm_thread_card(t) for t in visible])
    return render(request, "console/pipeline.html", {
        "columns": columns,
        "owner_chips": owner_chips,
        "track_chips": track_chips,
        "owner_filter": owner_filter,
        "track_filter": track_filter,
    })


@login_required
@require_POST
def thread_edit(request, thread_id):
    """Update a thread's stage / owner / next_action (the team's quick edit).

    Only the supplied fields are written (a blank field is treated as "no
    change" except next_action which can be cleared). The owner must be a valid
    user pk; anything else is ignored so a bad form never 500s.
    """
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    thread = get_object_or_404(OutreachThread, id=thread_id)

    updated = []
    stage = (request.POST.get("stage") or "").strip()
    if stage and stage in OutreachThread.Stage.values:
        thread.stage = stage
        updated.append("stage")

    if "next_action" in request.POST:
        thread.next_action = (request.POST.get("next_action") or "").strip()
        updated.append("next_action")

    owner_id = (request.POST.get("owner") or "").strip()
    if owner_id:
        from apps.accounts.models import User

        owner = User.objects.filter(pk=owner_id).first()
        if owner is not None:
            thread.owner = owner
            updated.append("owner")

    if updated:
        thread.save(update_fields=[*updated, "updated_at"])
        # log the change on the append-only timeline so nothing is silent.
        Activity.objects.create(
            thread=thread,
            activity_type="thread_updated",
            actor_type="human",
            actor=request.user,
            content_ref={"updated": updated, "stage": thread.stage},
        )
        messages.success(request, "Thread updated.")

    return _respond(request, thread, redirect_to="timeline")


@login_required
@require_POST
def set_stage(request, thread_id):
    """Move a thread to a new pipeline stage — the drag-and-drop write.

    Both pipelines (Joseph + console) POST here when a card is dropped in a new
    stage column. The posted value may be a raw ``OutreachThread.Stage`` OR a
    pipeline DISPLAY column key (discover/qualify/proposal/diligence/committed —
    what the board template emits in ``data-stage``); the column key is resolved
    to its canonical Stage via ``_COLUMN_TO_CRM_STAGE`` first so a drop onto ANY
    column advances the stage, not just "Committed" (the others would otherwise
    400 and the JS onEnd handler would revert the card). The single canonical
    endpoint validates the resolved target against ``OutreachThread.Stage`` (an
    unknown/missing stage → 400, no change), is role-gated by ``_can_manage_crm``
    (staff or owner/admin/campaign_owner), and appends an
    ``Activity(activity_type="stage_advanced")`` so a drag is never a silent
    mutation. Dropping a card back in its own column is a harmless no-op (no
    Activity). Returns 204 (the drop already updated the DOM optimistically); a
    full POST bounces back to the pipeline.
    """
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    from apps.joseph.views import _COLUMN_TO_CRM_STAGE

    posted = (request.POST.get("stage") or "").strip()
    # Accept either a raw Stage or a pipeline column key (mapped to its Stage).
    stage = _COLUMN_TO_CRM_STAGE.get(posted, posted)
    if not stage or stage not in OutreachThread.Stage.values:
        return HttpResponseBadRequest("Unknown stage.")

    thread = get_object_or_404(OutreachThread, id=thread_id)

    previous = thread.stage
    if stage != previous:
        thread.stage = stage
        thread.save(update_fields=["stage", "updated_at"])
        # log the move on the append-only timeline so nothing is silent.
        Activity.objects.create(
            thread=thread,
            activity_type="stage_advanced",
            actor_type="human",
            actor=request.user,
            content_ref={"from": previous, "to": stage},
        )

    if getattr(request, "htmx", False):
        return HttpResponse(status=204)
    return redirect("/joseph/pipeline/")


@login_required
@require_POST
def thread_activity(request, thread_id):
    """Append an Activity to the thread's append-only log."""
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    thread = get_object_or_404(OutreachThread, id=thread_id)

    activity_type = (request.POST.get("activity_type") or "note").strip() or "note"
    body = (request.POST.get("body") or "").strip()
    Activity.objects.create(
        thread=thread,
        activity_type=activity_type,
        actor_type="human",
        actor=request.user,
        content_ref={"body": body} if body else {},
    )
    # a logged touch updates the thread's last_touch (drives the no-reply flag).
    from django.utils import timezone

    thread.last_touch = timezone.now()
    thread.save(update_fields=["last_touch", "updated_at"])

    messages.success(request, "Activity logged.")
    return _respond(request, thread, redirect_to="timeline")


@login_required
@require_POST
def thread_task(request, thread_id):
    """Create a Task on the thread, owned by the acting user."""
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    thread = get_object_or_404(OutreachThread, id=thread_id)

    Task.objects.create(
        thread=thread,
        owner=request.user,
        type=(request.POST.get("type") or "follow_up").strip() or "follow_up",
        due=(request.POST.get("due") or None) or None,
        status=Task.Status.OPEN,
    )
    messages.success(request, "Task added.")
    return _respond(request, thread, redirect_to="tasks")


def _thread_context(thread) -> dict:
    """Build the compile-seam context from a Django ``OutreachThread`` — the
    entity (= org name, the synthesis target) plus the org / primary contact /
    track that sharpen the dossier. The CRM is canonical in Django (the strangler
    step), so this context is what agent-service compiles from (it no longer reads
    its own thread row)."""
    org_name = thread.org.name if thread.org_id else ""
    contact = thread.primary_contact
    return {
        "entity": org_name,
        "org": org_name,
        "contact": contact.full_name if contact else "",
        "track": thread.track or "",
    }


@login_required
@require_POST
def refresh_dossier(request, thread_id):
    """Recompile a thread's dossier from the Django thread context (the seam flip).

    Django posts the thread's ``{entity, org, contact, track}`` to the
    agent-service compile seam (``readers.compile_dossier_with_context`` →
    ``POST /agents/dossier/compile``) and stores the returned ``dossier_id`` back
    on the local ``OutreachThread``. Degrades quietly when the agent-service is
    down (the reader swallows ``AgentClientError`` → ``{}`` → no id written, no
    500). CSP-safe; HTMX swaps the timeline back, a full POST bounces to it."""
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM is not available for your role.")

    thread = get_object_or_404(OutreachThread, id=thread_id)

    result = readers.compile_dossier_with_context(_thread_context(thread))
    dossier_id = (result or {}).get("dossier_id")
    if dossier_id:
        thread.dossier_id = str(dossier_id)
        thread.save(update_fields=["dossier_id", "updated_at"])
        # log the recompile on the append-only timeline so nothing is silent.
        Activity.objects.create(
            thread=thread,
            activity_type="dossier_refreshed",
            actor_type="human",
            actor=request.user,
            content_ref={"dossier_id": thread.dossier_id, "sources": (result or {}).get("sources")},
        )
        messages.success(request, "Dossier refreshed — new intelligence compiled.")
    else:
        messages.error(request, "Couldn't refresh the dossier — intelligence service unavailable.")

    return _respond(request, thread, redirect_to="timeline")


def _respond(request, thread, *, redirect_to):
    """HTMX → swap the fresh partial; full POST → bounce back to the drawer tab."""
    if getattr(request, "htmx", False):
        if redirect_to == "tasks":
            return render(request, "crm/_task_list.html",
                          {"thread": thread, "tasks": _tasks(thread)})
        return render(request, "crm/_activity_timeline.html",
                      {"thread": thread, "activities": _activities(thread)})
    return redirect(f"/joseph/thread/{thread.id}/?tab={redirect_to}")
