"""Agent-service-backed console views (Slice G'). Mounted at /console/* via config/console_urls.py."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
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


@login_required
def drafts(request):
    sector = request.GET.get("sector", "")
    path = f"/content/items?sector={sector}" if sector else "/content/items"
    data = safe_get(path, default={"items": []})
    return render(request, "console/drafts.html",
                  {"items": (data or {}).get("items", []), "down": data is None})


@login_required
def draft_detail(request, content_id):
    data = safe_get(f"/content/items/{content_id}", default=None)
    return render(request, "console/draft_detail.html", {"c": data, "down": data is None})


def _publish_result_message(request, res):
    """Turn a ``publish_content_item`` result into a user-facing flash message.

    Returns True when the result was a clean success/schedule (caller redirects),
    False when the gate blocked the content (caller re-renders with findings).
    """
    if res.get("ok"):
        if res.get("scheduled"):
            messages.success(request, "Scheduled — it will publish at the chosen time through the gate.")
        elif res.get("published"):
            messages.success(request, f"Published to {res.get('accounts', 0)} channel(s).")
        else:
            messages.success(request, "Queued to publish through the gate.")
        return True
    reason = res.get("reason")
    if reason == "no_accounts":
        messages.error(request, "Connect a social account first, then publish.")
    elif reason == "empty":
        messages.error(request, "This draft has no body to publish.")
    elif reason == "gate_error":
        messages.error(request, "The compliance gate is unavailable right now — try again shortly.")
    elif reason == "gate_blocked":
        return False  # caller re-renders the draft with the gate findings
    else:
        messages.error(request, "Couldn't publish this draft.")
    return True


def _publish_or_schedule(request, content_id, scheduled_at):
    from apps.composer.console_publish import publish_content_item

    content = safe_get(f"/content/items/{content_id}", default=None)
    if not content:
        messages.error(request, "That draft is unavailable right now.")
        return redirect("console:drafts")
    res = publish_content_item(content, request.workspace, request.user, scheduled_at=scheduled_at)
    if _publish_result_message(request, res):
        return redirect("console:draft-detail", content_id=content_id)
    # Gate blocked — re-render the draft with the findings so the user can fix it.
    return render(request, "console/draft_detail.html", {
        "c": content, "down": False,
        "gate_blocked": True, "gate_verdict": res.get("verdict"),
        "gate_findings": _finding_lines(res.get("findings") or []),
    })


def _finding_lines(findings) -> list[str]:
    """Flatten gate findings (dicts or strings) into plain display lines."""
    out = []
    for f in findings:
        if isinstance(f, dict):
            out.append(str(f.get("msg") or f.get("message") or f.get("rule") or f))
        else:
            out.append(str(f))
    return out


@login_required
@require_POST
def draft_publish(request, content_id):
    """Publish a HERALD draft now — materialise a Post + run it through the gate."""
    return _publish_or_schedule(request, content_id, scheduled_at=None)


@login_required
@require_POST
def draft_schedule(request, content_id):
    """Schedule a HERALD draft for a chosen time (still gated at publish)."""
    raw = (request.POST.get("scheduled_at") or "").strip()
    dt = parse_datetime(raw) if raw else None
    if dt is None:
        messages.error(request, "Pick a valid date & time to schedule.")
        return redirect("console:draft-detail", content_id=content_id)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return _publish_or_schedule(request, content_id, scheduled_at=dt)


@login_required
def draft_edit(request, content_id):
    """Open this draft in the composer for editing (materialises a Post first)."""
    from apps.approvals.intake_publish import ensure_post_from_content_item

    content = safe_get(f"/content/items/{content_id}", default=None)
    if not content or request.workspace is None:
        messages.error(request, "That draft is unavailable right now.")
        return redirect("console:drafts")
    post = ensure_post_from_content_item(content, request.workspace, request.user)
    return redirect(reverse("composer:compose_edit",
                            kwargs={"workspace_id": request.workspace.id, "post_id": post.id}))
