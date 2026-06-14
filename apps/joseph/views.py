from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.common.agent_client import AgentClientError, agent_get, agent_post, agent_put

_CHANNELS = ["linkedin", "email", "x", "voice"]


def _safe_get(path: str) -> dict:
    """Fetch from agent-service, tolerating an unconfigured/down service."""
    try:
        return agent_get(path) or {}
    except AgentClientError:
        return {}


def _can_access_joseph(request) -> bool:
    """Gate for Joseph's principal surface (home, brief, pipeline, drawer,
    knowledge, content). Joseph's platform is for the principal and the people
    who run it with him — staff (superuser escape hatch) OR an owner/admin/
    principal workspace role (reusing the membership RBACMiddleware resolved).
    Every Joseph view added in this spine is gated by this."""
    if getattr(request.user, "is_staff", False):
        return True
    m = getattr(request, "workspace_membership", None)
    return bool(m and m.workspace_role in ("owner", "admin", "principal"))


def _can_manage_voice(request) -> bool:
    """The voice profile is a global, org-wide brand-voice config (not
    workspace-scoped), so mere authentication is not enough to read or mutate
    it — that is the 'any authenticated member can touch a sensitive object'
    gap closed for approvals in 94f732e. Gate on an owner/admin workspace role
    (reusing the membership RBACMiddleware already resolved) or staff."""
    if getattr(request.user, "is_staff", False):
        return True
    m = getattr(request, "workspace_membership", None)
    return bool(m and m.workspace_role in ("owner", "admin"))


@login_required
def voice_editor(request):
    if not _can_manage_voice(request):
        return HttpResponseForbidden("You are not authorized to manage the brand voice.")
    data = _safe_get("/voice/joseph")
    body = (data or {}).get("body", {})
    length_by_channel = body.get("length_by_channel") or {}
    channel_lengths = [(c, length_by_channel.get(c, "")) for c in _CHANNELS]

    proposals_data = _safe_get("/voice/joseph/proposals")
    proposals = proposals_data.get("proposals", []) if isinstance(proposals_data, dict) else (proposals_data or [])

    return render(
        request,
        "joseph/voice_editor.html",
        {
            "body": body,
            "channels": _CHANNELS,
            "channel_lengths": channel_lengths,
            "proposals": proposals,
        },
    )


@login_required
@require_POST
def voice_save(request):
    if not _can_manage_voice(request):
        return HttpResponseForbidden("You are not authorized to manage the brand voice.")
    body = {
        "tone": request.POST.get("tone", "").strip(),
        "openers": request.POST.get("openers", "").strip(),
        "banned_phrases": [p.strip() for p in request.POST.get("banned_phrases", "").split(",") if p.strip()],
        "signature_moves": [s.strip() for s in request.POST.get("signature_moves", "").split("\n") if s.strip()],
        "length_by_channel": {c: request.POST.get(f"length_by_channel_{c}", "").strip() for c in _CHANNELS},
        "hooks_by_audience": {},  # edited in a later iteration; preserve existing on round-trip
    }
    # preserve hooks_by_audience from current profile (tolerate service down)
    current = _safe_get("/voice/joseph").get("body", {})
    body["hooks_by_audience"] = current.get("hooks_by_audience", {})
    try:
        agent_put("/voice/joseph", {"body": body})
    except AgentClientError:
        messages.error(request, "Couldn't save the voice profile — intelligence service unavailable.")
    return redirect("joseph:voice")


@login_required
@require_POST
def voice_apply_proposal(request, proposal_id):
    if not _can_manage_voice(request):
        return HttpResponseForbidden("You are not authorized to manage the brand voice.")
    try:
        agent_post(f"/voice/joseph/proposals/{proposal_id}/apply")
    except AgentClientError:
        messages.error(request, "Couldn't apply the proposal — intelligence service unavailable.")
    return redirect("joseph:voice")


@login_required
@require_POST
def voice_dismiss_proposal(request, proposal_id):
    if not _can_manage_voice(request):
        return HttpResponseForbidden("You are not authorized to manage the brand voice.")
    try:
        agent_post(f"/voice/joseph/proposals/{proposal_id}/dismiss")
    except AgentClientError:
        messages.error(request, "Couldn't dismiss the proposal — intelligence service unavailable.")
    return redirect("joseph:voice")
