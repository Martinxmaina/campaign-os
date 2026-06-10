"""Agent-service-backed console: pipeline, notifications, brain (Slice G')."""
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.common.agent_client import agent_post
from apps.common.safe import safe_get
from apps.content_intake.sector_map import map_pillar_to_sector

logger = logging.getLogger(__name__)

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
    raw = safe_get("/news/digest" + qs, default=None)
    down = raw is None
    data = raw if raw is not None else dict(_NEWS_DEFAULT)
    return render(
        request,
        "console/news.html",
        {
            "items": data.get("items", []),
            "counts": data.get("counts", {}),
            "generated_at": data.get("generated_at"),
            "sector": sector or "all",
            "africa": africa,
            "down": down,
        },
    )


@login_required
@require_POST
def news_draft(request):
    sector = map_pillar_to_sector(request.POST.get("sector", ""))
    title = request.POST.get("title", "")
    summary = request.POST.get("summary", "")
    link = request.POST.get("link", "")
    source = request.POST.get("source", "")
    brief = "\n".join(p for p in [title, summary, f"Source: {source}" if source else "", link] if p)
    try:
        agent_post("/agents/herald/draft", {"sector": sector, "brief": brief})
    except Exception:
        logger.warning("news_draft: agent_post failed", exc_info=True)
    return redirect("console:approvals")
