from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.common.agent_client import AgentClientError, agent_get, agent_post, agent_put
from apps.joseph import readers
from apps.joseph.intelligence import JosephIntelligence

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


def _is_mobile(request) -> bool:
    """Pick the editorial (mobile) vs operational (desktop) surface.

    ``?view=mobile|desktop`` forces it explicitly (used by the in-app toggle and
    tests); otherwise we sniff the User-Agent for a phone hint. One view, two
    content-differentiated templates — not a resize.
    """
    view = (request.GET.get("view") or "").lower()
    if view == "mobile":
        return True
    if view == "desktop":
        return False
    ua = (request.META.get("HTTP_USER_AGENT") or "").lower()
    return any(h in ua for h in ("iphone", "android", "mobile", "ipod"))


@login_required
def home(request):
    """Joseph's home — the single place he opens before every conversation.

    Mobile = one screen of editorial signal (Today, Action queue, Red threads,
    Your content). Desktop = the operational shell (fleshed out in Task 7). Both
    share the same view data and the same ``JosephIntelligence`` seam; every
    agent-service read degrades to an empty state when the service is down."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    intel = JosephIntelligence()
    workspace = getattr(request, "workspace", None)

    # Action queue — merged notifications + Joseph's pending posts + unlinked events.
    actions = intel.proposals(workspace=workspace, user=request.user)

    # Red threads — agent-service threads flagged red, owned by Joseph.
    red_threads = readers.list_threads(traffic_light="red", owner="joseph")

    # Today's calendar events (linked + unlinked) for this workspace.
    today_events = _today_events(workspace)

    # Joseph's personal content queue (a teaser strip; full surface is Task 9).
    content = _joseph_content(workspace, request.user)

    context = {
        "today": timezone.localdate(),
        "today_events": today_events,
        "actions": actions,
        "action_count": len(actions),
        "red_threads": red_threads,
        "red_thread_count": len(red_threads),
        "content": content,
        "is_mobile": _is_mobile(request),
    }
    template = "joseph/home_mobile.html" if context["is_mobile"] else "joseph/home_desktop.html"
    return render(request, template, context)


def _today_events(workspace):
    """CalendarEvents starting today for the workspace (empty until Task 10 syncs)."""
    try:
        from apps.joseph.models import CalendarEvent
    except (ImportError, LookupError):
        return []
    try:
        today = timezone.localdate()
        qs = CalendarEvent.objects.filter(start__date=today)
        if workspace is not None:
            qs = qs.filter(workspace=workspace)
        return list(qs)
    except Exception:
        return []


def _joseph_content(workspace, user):
    """Posts assigned to / authored by Joseph, newest scheduling first (teaser)."""
    from django.db.models import Q

    from apps.composer.models import Post

    try:
        qs = Post.objects.filter(Q(review_assignee=user) | Q(author=user))
        if workspace is not None:
            qs = qs.filter(workspace=workspace)
        return list(qs.order_by("-scheduled_at", "-created_at")[:5])
    except Exception:
        return []


@login_required
def brief(request, thread_id):
    """Joseph's dossier brief — the screen he opens before a conversation.

    L0 (default) is the editorial card: WHO / WHY NOW / HOOK / RED FLAGS /
    WARM PATH / FRESHNESS mapped onto the existing Dossier by
    ``JosephIntelligence`` (no agent-service change). ``?tier=l1`` returns the
    dossier ``body_md``; ``?tier=l2`` the linked wiki page body (else body_md).

    The tier toggle is an HTMX swap (CSP-safe ``hx-get``/``hx-target``): an
    ``HX-Request`` returns just the body partial; a full GET renders the page.
    When the agent-service is down (or the thread has no dossier) the readers
    degrade to empty defaults and the card shows a "Compile" CTA — never a 500.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    tier = (request.GET.get("tier") or "l0").lower()
    if tier not in ("l0", "l1", "l2"):
        tier = "l0"

    intel = JosephIntelligence()
    card = intel.brief(thread_id, tier)

    context = {
        "thread_id": thread_id,
        "tier": tier,
        "card": card,
        "has_dossier": card.get("has_dossier", False),
        "is_mobile": _is_mobile(request),
    }

    # HTMX tier toggle → swap only the body partial (l1/l2). l0 is the card.
    if getattr(request, "htmx", False):
        if tier == "l0":
            return render(request, "joseph/_l0_card.html", context)
        return render(request, "joseph/_brief_body.html", context)

    return render(request, "joseph/brief.html", context)


@login_required
@require_POST
def brief_refresh(request, thread_id):
    """Recompile the dossier for a thread (POST /threads/{id}/dossier via lead
    token), then bounce back to the brief. Degrades quietly if the service is
    down (the reader swallows AgentClientError → empty dict)."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")
    result = readers.compile_dossier(thread_id)
    if result:
        messages.success(request, "Refreshing the dossier — new intelligence is compiling.")
    else:
        messages.error(request, "Couldn't refresh the dossier — intelligence service unavailable.")
    return redirect("joseph:brief", thread_id=thread_id)


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
