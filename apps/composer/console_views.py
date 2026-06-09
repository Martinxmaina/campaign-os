"""Agent-service-backed console views (Slice G'). Mounted at /console/* via config/console_urls.py."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.common.agent_client import agent_post
from apps.common.safe import safe_get


@login_required
def ideas(request):
    week = request.GET.get("week", "")
    path = f"/ideas?week={week}" if week else "/ideas"
    data = safe_get(path, default={"items": []})
    return render(request, "console/ideas.html",
                  {"items": (data or {}).get("items", []), "week": week, "down": data is None})


@login_required
@require_POST
def idea_decide(request, idea_id):
    decision = request.POST.get("decision", "")
    try:
        agent_post(f"/ideas/{idea_id}/decide", {"decision": decision})
    except Exception:
        pass
    return redirect("console:ideas")
