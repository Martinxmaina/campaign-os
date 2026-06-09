"""Agent-service-backed console: pipeline, notifications, brain (Slice G')."""
from django.contrib.auth.decorators import login_required
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
