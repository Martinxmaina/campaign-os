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
    body = {"decision": request.POST.get("decision", "")}
    edit = request.POST.get("edit_text")
    if edit:
        body["edit_text"] = edit
    try:
        agent_post(f"/approvals/{approval_id}/decide", body)
    except Exception:
        pass
    return redirect("console:approvals")
