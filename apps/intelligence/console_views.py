"""Agent-service-backed console: pipeline, notifications, brain (Slice G')."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.common.agent_client import agent_post
from apps.common.safe import safe_get

_LIGHTS = ["green", "amber", "red"]


@login_required
def pipeline(request):
    data = safe_get("/threads", default={"items": []})
    items = (data or {}).get("items", [])
    cols = {l: [t for t in items if (t.get("traffic_light") or "green") == l] for l in _LIGHTS}
    return render(request, "console/pipeline.html", {"cols": cols, "lights": _LIGHTS, "down": data is None})


@login_required
def notifications(request):
    data = safe_get("/notifications?unread=true", default={"items": []})
    return render(request, "console/notifications.html",
                  {"items": (data or {}).get("items", []), "down": data is None})


@login_required
@require_POST
def notification_read(request, notification_id):
    try:
        agent_post(f"/notifications/{notification_id}/read", {})
    except Exception:
        pass
    return redirect("console:notifications")


@login_required
def graph_json(request):
    data = safe_get("/graph", default={"nodes": [], "edges": []})
    return JsonResponse(data or {"nodes": [], "edges": []})


@login_required
def brain(request):
    return render(request, "console/brain.html", {})


_NEWS_DEFAULT = {"items": [], "counts": {}, "generated_at": None}


@login_required
def news(request):
    sector = request.GET.get("sector", "")
    africa = request.GET.get("africa", "")
    params = []
    if sector:
        params.append(f"sector={sector}")
    if africa:
        params.append(f"africa={africa}")
    qs = ("?" + "&".join(params)) if params else ""
    data = safe_get("/news/digest" + qs, default=dict(_NEWS_DEFAULT))
    data = data or dict(_NEWS_DEFAULT)
    return render(
        request,
        "console/news.html",
        {
            "items": data.get("items", []),
            "counts": data.get("counts", {}),
            "generated_at": data.get("generated_at"),
            "sector": sector or "all",
            "africa": africa,
            "down": data is None,
        },
    )


@login_required
@require_POST
def news_draft(request):
    sector = request.POST.get("sector", "")
    title = request.POST.get("title", "")
    summary = request.POST.get("summary", "")
    link = request.POST.get("link", "")
    source = request.POST.get("source", "")
    brief = "\n".join(p for p in [title, summary, f"Source: {source}" if source else "", link] if p)
    try:
        agent_post("/agents/herald/draft", {"sector": sector, "brief": brief})
    except Exception:
        pass
    return redirect("console:approvals")
