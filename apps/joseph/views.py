from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
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

    is_mobile = _is_mobile(request)

    context = {
        "today": timezone.localdate(),
        "today_events": today_events,
        "actions": actions,
        "action_count": len(actions),
        "red_threads": red_threads,
        "red_thread_count": len(red_threads),
        "content": content,
        "is_mobile": is_mobile,
    }

    # The desktop operational surface adds a capital funnel + an escalations
    # strip on top of the shared home data. Both degrade to empty/zero when the
    # agent-service is down (the readers swallow AgentClientError) — never a 500.
    if not is_mobile:
        context["funnel"] = _capital_funnel()
        context["escalations"] = [a for a in actions if a.get("urgent")]

    template = "joseph/home_mobile.html" if is_mobile else "joseph/home_desktop.html"
    return render(request, template, context)


# The pipeline statuses that make up Joseph's capital funnel, in flow order.
_FUNNEL_STATUSES = [
    ("draft", "Draft"),
    ("scheduled", "Scheduled"),
    ("published", "Published"),
]


def _capital_funnel() -> list[dict]:
    """Draft → Scheduled → Published content counts for the desktop funnel.

    Each count comes from ``readers.list_content(status=...)`` (the fixed
    agent-service ``/content/items`` route). The reader returns ``[]`` when the
    service is down, so a funnel stage degrades to a zero count rather than a 500.
    """
    return [
        {"key": key, "label": label, "count": len(readers.list_content(status=key))}
        for key, label in _FUNNEL_STATUSES
    ]


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
def notifications_json(request):
    """The notification bell's poll endpoint — unread count + the items.

    Joseph's surface (and its installed PWA) polls this every ~30s to keep the
    bell badge live. It reads the same agent-service ``/notifications?unread``
    route through ``readers.list_notifications``, which swallows
    ``AgentClientError`` → an agent outage yields ``{"count": 0, "items": []}``
    (a 200 empty payload), never a 500. Gated by ``_can_access_joseph`` so we
    never query the intelligence plane for a non-capable user."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")
    items = readers.list_notifications(unread=True)
    return JsonResponse({"count": len(items), "items": items})


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


_PIPELINE_STAGES = [
    ("discover", "Discover"),
    ("qualify", "Qualify"),
    ("proposal", "Proposal"),
    ("diligence", "Diligence"),
    ("committed", "Committed"),
]
_CATCH_ALL = ("_other", "Other")


@login_required
def pipeline(request):
    """Joseph's deal-flow board — a traffic-light kanban grouped by stage.

    Threads from agent-service are bucketed into the five ordered stage columns
    (Discover → Committed) with a catch-all so an unrecognised stage is never
    silently dropped. Each card shows the org, a traffic-light dot, the quintile
    and the next action, and links into the thread drawer (Task 6). When the
    agent-service is down the reader returns ``[]`` → the columns render empty,
    never a 500.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    threads = readers.list_threads()

    # Bucket by stage, preserving the canonical column order + a catch-all tail.
    buckets: dict[str, list] = {key: [] for key, _ in _PIPELINE_STAGES}
    buckets[_CATCH_ALL[0]] = []
    known = set(buckets)
    for t in threads:
        stage = (t.get("stage") or "").lower()
        buckets[stage if stage in known and stage != _CATCH_ALL[0] else _CATCH_ALL[0]].append(t)

    columns = [
        {"key": key, "label": label, "threads": buckets[key], "count": len(buckets[key])}
        for key, label in _PIPELINE_STAGES
    ]
    if buckets[_CATCH_ALL[0]]:
        columns.append({
            "key": _CATCH_ALL[0], "label": _CATCH_ALL[1],
            "threads": buckets[_CATCH_ALL[0]], "count": len(buckets[_CATCH_ALL[0]]),
        })

    return render(request, "joseph/pipeline.html", {"columns": columns})


_DRAWER_TABS = [
    ("brief", "Brief"),
    ("timeline", "Timeline"),
    ("intelligence", "Intelligence"),
    ("tasks", "Tasks"),
    ("deck", "Deck"),
    ("sequence", "Sequence"),
]
_DRAWER_TAB_KEYS = {key for key, _ in _DRAWER_TABS}


@login_required
def thread_drawer(request, thread_id):
    """Joseph's thread drawer — the full operational view of one deal thread.

    A header (org + stage + score + traffic-light) with actions (Request deck /
    Capture → stubs for later phases, Escalate → creates a notification) over
    six HTMX-swappable tabs: Brief / Timeline / Intelligence / Tasks / Deck /
    Sequence. Brief reuses the L0 card; Intelligence pulls the org's wiki page +
    org-filtered news; Deck/Sequence are present-but-stubbed so later phases drop
    in without a re-layout.

    A full GET renders the shell (defaulting to the Brief tab); an ``HX-Request``
    with ``?tab=`` returns only that tab's partial (CSP-safe ``hx-get``). Every
    agent-service read degrades to a safe default when the service is down —
    the drawer renders an empty state, never a 500.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    tab = (request.GET.get("tab") or "brief").lower()
    if tab not in _DRAWER_TAB_KEYS:
        tab = "brief"

    thread = readers.get_thread(thread_id)
    context = {
        "thread_id": thread_id,
        "thread": thread,
        "tab": tab,
        "tabs": _DRAWER_TABS,
    }
    context.update(_drawer_tab_context(tab, thread_id, thread))

    # HTMX tab switch → swap only the tab partial; a full GET renders the shell.
    if getattr(request, "htmx", False):
        return render(request, f"joseph/_drawer_tabs/{tab}.html", context)
    return render(request, "joseph/thread_drawer.html", context)


def _drawer_tab_context(tab: str, thread_id: str, thread: dict) -> dict:
    """Compose the per-tab context (only the active tab does any work)."""
    if tab == "brief":
        return {"card": JosephIntelligence().brief(thread_id, "l0")}
    if tab == "timeline":
        state = thread.get("state") or {}
        return {"timeline": state.get("timeline") or []}
    if tab == "intelligence":
        org = thread.get("org") or ""
        from django.utils.text import slugify

        page = readers.get_page(slugify(org), tier="l1") if org else {}
        return {"org": org, "page": page, "news": readers.news_about(org) if org else []}
    # tasks / deck / sequence carry no extra context (stubbed surfaces).
    return {}


@login_required
@require_POST
def thread_escalate(request, thread_id):
    """Escalate a thread to Joseph's attention by creating an (urgent)
    notification on the intelligence plane. Degrades quietly when the service is
    down (the reader swallows AgentClientError → empty dict)."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")
    thread = readers.get_thread(thread_id)
    org = (thread or {}).get("org") or thread_id
    result = readers.create_notification(
        kind="escalation",
        body=f"Escalated: {org} needs your attention.",
        thread_id=thread_id,
        urgent=True,
        action={"href": f"/joseph/thread/{thread_id}/"},
    )
    if result:
        messages.success(request, "Escalated — flagged for your attention.")
    else:
        messages.error(request, "Couldn't escalate — intelligence service unavailable.")
    return redirect("joseph:thread", thread_id=thread_id)


# The wiki entity types Joseph filters by (chips in the knowledge browser),
# matching the agent-service knowledge model's entity_type vocabulary.
_KNOWLEDGE_ENTITY_TYPES = ["funder", "org", "person", "initiative", "topic"]


@login_required
def knowledge(request):
    """Joseph's knowledge browser — search the agent-service wiki.

    A free-text query (``?q=``) plus entity_type filter chips
    (funder/org/person/initiative/topic, ``?entity_type=``) over
    ``readers.search_pages`` (the fixed ``/knowledge/pages`` route). Each result
    card links into the page detail. When the agent-service is down the reader
    returns ``[]`` → the browser renders an empty state, never a 500.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    q = (request.GET.get("q") or "").strip()
    entity_type = (request.GET.get("entity_type") or "").strip().lower()
    if entity_type and entity_type not in _KNOWLEDGE_ENTITY_TYPES:
        entity_type = ""

    pages = readers.search_pages(q=q, entity_type=entity_type)

    return render(request, "joseph/knowledge.html", {
        "q": q,
        "entity_type": entity_type,
        "entity_types": _KNOWLEDGE_ENTITY_TYPES,
        "pages": pages,
    })


@login_required
def knowledge_detail(request, slug):
    """A single wiki page — title + tiered body + outgoing links + revisions.

    The L0/L1/L2 tier toggle is an HTMX swap (CSP-safe ``hx-get``/``hx-target``):
    an ``HX-Request`` returns just the body partial; a full GET renders the page
    (defaulting to L1, the overview). Outgoing wiki links render as in-app links
    to other knowledge pages (slugified). Revisions come from the fixed
    ``/knowledge/pages/{slug}/revisions`` route. Every read degrades to a safe
    default when the agent-service is down → an empty state, never a 500.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    tier = (request.GET.get("tier") or "l1").lower()
    if tier not in ("l0", "l1", "l2"):
        tier = "l1"

    page = readers.get_page(slug, tier=tier)

    context = {
        "slug": slug,
        "tier": tier,
        "page": page,
        "has_page": bool(page),
    }

    # HTMX tier toggle → swap only the body partial; a full GET renders the page
    # (with revisions, which don't change between tiers).
    if getattr(request, "htmx", False):
        return render(request, "joseph/_knowledge_body.html", context)

    context["revisions"] = readers.page_revisions(slug)
    return render(request, "joseph/knowledge_detail.html", context)


def _gate_findings(post) -> list[dict]:
    """Gate findings on Joseph's own post, read from its blocked PlatformPosts.

    The publish gate marks a blocked PlatformPost ``failed`` with a
    ``GATE BLOCK: <reason>`` ``publish_error`` (apps/publisher/engine._block).
    We surface those as inline findings (platform + reason) so Joseph sees what
    the gate caught and can override with an audit, rather than silently
    unblocking. Pure Django read — no agent dependency, never raises.
    """
    findings = []
    try:
        for pp in post.platform_posts.all():
            err = (pp.publish_error or "").strip()
            if not err:
                continue
            if err.upper().startswith("GATE BLOCK:") or pp.status == "failed":
                reason = err.split(":", 1)[1].strip() if ":" in err else err
                findings.append({"platform": pp.platform, "reason": reason})
    except Exception:
        return []
    return findings


@login_required
def content_queue(request):
    """Joseph's personal content queue — the posts he owns or must approve.

    Lists Posts assigned to (``review_assignee``) or authored by Joseph, newest
    publish-date first. Each card surfaces gate findings (from a blocked
    PlatformPost) with an audited "Override (logged)" action — overriding writes
    an ``ApprovalAction`` and approves the post (an override is logged, not a
    silent unblock). "Draft new" links to the composer carrying
    ``voice_user=joseph`` so HERALD drafts in Joseph's voice.

    Reads only Django data (no agent-service call), so there is nothing to 500
    on. Gated by ``_can_access_joseph``; CSP-safe (POST forms, no inline handlers).
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    from django.db.models import Q

    from apps.composer.models import Post

    workspace = getattr(request, "workspace", None)
    qs = Post.objects.filter(Q(review_assignee=request.user) | Q(author=request.user))
    if workspace is not None:
        qs = qs.filter(workspace=workspace)
    posts = list(
        qs.prefetch_related("platform_posts__social_account")
        .order_by("-scheduled_at", "-created_at")
    )

    items = [{"post": p, "findings": _gate_findings(p)} for p in posts]

    return render(request, "joseph/content_queue.html", {
        "items": items,
        "flagged_count": sum(1 for i in items if i["findings"]),
    })


@login_required
@require_POST
def content_override(request, post_id):
    """Audited override of a gate finding on one of Joseph's own posts.

    Not a silent unblock: it writes an ``ApprovalAction`` (APPROVED, with an
    "Override (logged)" comment naming the overridden findings) and moves the
    post's ``review_state`` to APPROVED. Gated by ``_can_access_joseph``.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    from django.db.models import Q
    from django.shortcuts import get_object_or_404

    from apps.approvals.models import ApprovalAction
    from apps.composer.models import Post

    qs = Post.objects.filter(Q(review_assignee=request.user) | Q(author=request.user))
    workspace = getattr(request, "workspace", None)
    if workspace is not None:
        qs = qs.filter(workspace=workspace)
    post = get_object_or_404(qs, pk=post_id)

    findings = _gate_findings(post)
    reasons = ", ".join(f["reason"] for f in findings) or "no active findings"
    ApprovalAction.objects.create(
        post=post,
        user=request.user,
        action=ApprovalAction.ActionType.APPROVED,
        comment=f"Override (logged): gate finding overridden by principal — {reasons}",
    )
    post.review_state = Post.ReviewState.APPROVED
    post.save(update_fields=["review_state", "updated_at"])

    messages.success(request, "Override logged — the post is approved.")
    return redirect("joseph:content")


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
