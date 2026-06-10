"""Agent-service-backed AI approvals (Slice G'). Distinct from native PlatformPost approvals."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.common.agent_client import agent_post
from apps.common.safe import safe_get


@login_required
def ai_approvals(request):
    data = safe_get("/approvals?assignee=me", default={"items": []})
    return render(request, "console/approvals.html",
                  {"items": (data or {}).get("items", []), "down": data is None})


@login_required
@require_POST
def approval_decide(request, approval_id):
    decision = request.POST.get("decision", "")
    body = {"decision": decision}
    edit = request.POST.get("edit_text")
    if edit:
        body["edit_text"] = edit
    try:
        agent_post(f"/approvals/{approval_id}/decide", body)
    except Exception:
        # The agent-service is the system of record for the decision. If the
        # decide call failed, do NOT create a local Post — that would diverge
        # the two systems (a publishable Post with no recorded approval).
        return redirect("console:approvals")

    if decision == "approve":
        _try_create_post(request)

    return redirect("console:approvals")


def _try_create_post(request):
    """On approve, pull the content item and create a publishable Post.

    The content id is the approval's ``target_ref`` (a content_item id). It is
    submitted by the approvals form as a hidden field, so no extra round-trip
    to the agent-service is needed (and there is no GET /approvals/{id} route).
    """
    from apps.approvals.intake_publish import create_post_from_content
    from apps.content_intake.models import ContentIntake

    content_id = request.POST.get("target_ref")
    if not content_id:
        return
    content = safe_get(f"/content/items/{content_id}", default=None)
    if not content:
        return
    intake = ContentIntake.objects.filter(
        workspace=getattr(request, "workspace", None),
        herald_content_id=str(content_id),
    ).first()
    if intake is None:
        return
    try:
        create_post_from_content(content, intake)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("post creation from approval failed")
