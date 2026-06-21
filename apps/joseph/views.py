from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.common.agent_client import AgentClientError, agent_get, agent_post, agent_put
from apps.joseph import readers
from apps.joseph.intelligence import JosephIntelligence
from apps.joseph.tasks import extract_meeting

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

    # Red threads — local CRM threads flagged red (the canonical source).
    red_threads = [_crm_thread_card(t) for t in _crm_threads(traffic_light="red")]

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
        # The "This week" stat strip + a compact by-stage chart are shared by BOTH
        # surfaces (mobile shows the one compact chart; desktop the full trio).
        # Computed from the CANONICAL Django sources (CRM threads + Activity log +
        # CalendarEvent), never the agent-service, so they survive an outage.
        "week_stats": _week_stats(workspace, request.user),
        "chart_by_stage": _chart_by_stage(),
    }

    # The desktop operational surface adds a capital funnel + an escalations
    # strip + the full Today chart trio on top of the shared home data. Both
    # degrade to empty/zero when the agent-service is down (the readers swallow
    # AgentClientError) — never a 500.
    if not is_mobile:
        context["funnel"] = _capital_funnel()
        context["by_track"] = _pipeline_by_track()
        context["escalations"] = [a for a in actions if a.get("urgent")]
        context["chart_by_track"] = _chart_by_track()
        context["chart_quintile"] = _chart_quintile()

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


# Capital tracks in display order; a thread outside these falls into "Other".
_TRACKS = [
    ("ai10bn", "AI 10Bn"),
    ("core", "Core programs"),
    ("waiis", "WAIIS"),
    ("energy", "Energy access"),
]


def _pipeline_by_track() -> list[dict]:
    """Thread counts grouped by track for the desktop "Pipeline by track" bars.

    Counts local CRM threads by track (the canonical source). This is an honest
    count-by-track rather than a fabricated dollar funnel. An empty DB → all-zero
    bars, never a 500.
    """
    counts: dict[str, int] = {}
    for t in _crm_threads():
        key = (t.track or "other").lower()
        counts[key] = counts.get(key, 0) + 1
    known = dict(_TRACKS)
    rows = [{"key": k, "label": lbl, "count": counts.get(k, 0)} for k, lbl in _TRACKS]
    other = sum(v for k, v in counts.items() if k not in known)
    if other:
        rows.append({"key": "other", "label": "Other", "count": other})
    top = max((r["count"] for r in rows), default=0)
    for r in rows:
        r["pct"] = round(100 * r["count"] / top) if top else 0
    return rows


# ── Today charts (Chart.js datasets) ─────────────────────────────────────────
# Each builder returns a ``{"labels": [...], "data": [...]}`` dict — the exact
# shape the template ships to Chart.js via ``json_script``. All three read the
# canonical Django CRM (no agent-service), bucket by an in-memory tally so an
# empty DB yields a valid empty/zero dataset (Chart.js never crashes on it).


def _chart_by_track() -> dict:
    """Thread count per capital track, in the canonical track display order,
    dropping tracks with zero threads (an empty DB → empty dataset)."""
    counts: dict[str, int] = {}
    for t in _crm_threads():
        key = (t.track or "other").lower()
        counts[key] = counts.get(key, 0) + 1
    labels, data = [], []
    for key, label in _TRACKS:
        if counts.get(key):
            labels.append(label)
            data.append(counts[key])
    other = sum(v for k, v in counts.items() if k not in dict(_TRACKS))
    if other:
        labels.append("Other")
        data.append(other)
    return {"labels": labels, "data": data}


def _chart_by_stage() -> dict:
    """Thread count per pipeline stage, in ``OutreachThread.Stage`` order,
    dropping stages with zero threads (an empty DB → empty dataset)."""
    from apps.crm.models import OutreachThread

    counts: dict[str, int] = {}
    for t in _crm_threads():
        counts[t.stage] = counts.get(t.stage, 0) + 1
    labels, data = [], []
    for value, label in OutreachThread.Stage.choices:
        if counts.get(value):
            labels.append(label)
            data.append(counts[value])
    return {"labels": labels, "data": data}


def _chart_quintile() -> dict:
    """Thread count per 1–5 quintile — always five buckets (Q1..Q5) so the
    doughnut renders consistently; a quintile of 0/None/out-of-range is ignored
    (it has no bucket). An empty DB → five zero buckets, never a crash."""
    buckets = [0, 0, 0, 0, 0]
    for t in _crm_threads():
        try:
            q = int(t.quintile or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= q <= 5:
            buckets[q - 1] += 1
    return {"labels": ["Q1", "Q2", "Q3", "Q4", "Q5"], "data": buckets}


def _week_start():
    """Monday 00:00 (local) of the current week, as an aware datetime."""
    today = timezone.localdate()
    monday = today - timezone.timedelta(days=today.weekday())
    return timezone.make_aware(
        timezone.datetime(monday.year, monday.month, monday.day)
    )


def _week_stats(workspace, user) -> dict:
    """The "This week" strip: meetings booked, threads advanced, replies logged
    and content drafts — all from canonical Django sources (CalendarEvent +
    Activity + Post). Every count degrades to 0 on an empty DB / bad data, never
    a 500."""
    from apps.crm.models import Activity

    start = _week_start()

    advanced = Activity.objects.filter(
        activity_type="stage_advanced", created_at__gte=start
    ).count()
    replies = Activity.objects.filter(
        activity_type="email_reply", created_at__gte=start
    ).count()

    meetings = 0
    try:
        from apps.joseph.models import CalendarEvent

        cq = CalendarEvent.objects.filter(start__gte=start)
        if workspace is not None:
            cq = cq.filter(workspace=workspace)
        meetings = cq.count()
    except Exception:
        meetings = 0

    drafts = 0
    try:
        from django.db.models import Q

        from apps.composer.models import Post

        # Posts Joseph owns/must approve that haven't cleared review yet — the
        # work-in-progress slice (pending / freshly-drafted / changes-requested),
        # i.e. everything short of APPROVED or REJECTED.
        pq = Post.objects.filter(Q(review_assignee=user) | Q(author=user)).filter(
            review_state__in=[
                Post.ReviewState.NONE,
                Post.ReviewState.PENDING,
                Post.ReviewState.CHANGES_REQUESTED,
            ]
        )
        if workspace is not None:
            pq = pq.filter(workspace=workspace)
        drafts = pq.count()
    except Exception:
        drafts = 0

    return {
        "meetings_this_week": meetings,
        "threads_advanced": advanced,
        "replies": replies,
        "drafts": drafts,
    }


def _thread_days_since_touch(last_touch_at):
    """Whole days since a thread's last touch, from the ISO timestamp the
    ``/threads`` serializer returns. ``None`` when absent/unparseable."""
    if not last_touch_at:
        return None
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(str(last_touch_at).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return max((timezone.now() - ts).days, 0)


def _quintile_dots(quintile) -> str:
    """Filled/empty dot row for a 1–5 quintile (4 → '●●●●○'); '' for 0/None/out-of-range."""
    try:
        q = int(quintile or 0)
    except (TypeError, ValueError):
        return ""
    return "●" * q + "○" * (5 - q) if 1 <= q <= 5 else ""


def _annotate_thread(t: dict) -> dict:
    """Add UI-derived fields (days_since_touch, quintile_dots) to a thread dict in place."""
    t["days_since_touch"] = _thread_days_since_touch(t.get("last_touch_at"))
    t["quintile_dots"] = _quintile_dots(t.get("quintile"))
    return t


# CRM OutreachThread.Stage → the pipeline's display column key. Stages outside
# this map (targeted/contracted/closed/...) fall into the catch-all "Other"
# column so nothing silently disappears from the board.
_CRM_STAGE_TO_COLUMN = {
    "engaged": "qualify",
    "proposal_sent": "proposal",
    "in_discussion": "diligence",
    "committed": "committed",
}

# Pipeline display column key → the canonical CRM Stage a drop onto that column
# should set. This is the inverse of ``_CRM_STAGE_TO_COLUMN`` plus the "discover"
# column (the earliest, no-source-stage bucket) → ``targeted``. ``set_stage``
# resolves a posted column key through this map so dragging a card to ANY column
# (not just "Committed") advances the stage — the template emits these keys in
# ``data-stage``, so without this 5 of 6 columns would 400 and the drop reverts.
_COLUMN_TO_CRM_STAGE = {
    "discover": "targeted",
    "qualify": "engaged",
    "proposal": "proposal_sent",
    "diligence": "in_discussion",
    "committed": "committed",
}


def _crm_thread_card(thread) -> dict:
    """Adapt a local ``apps.crm.OutreachThread`` into the dict shape the Joseph
    pipeline/briefs/home templates already render — the CRM is now canonical
    (the strangler step), so the surface reads Django querysets, not the
    agent-service ``/threads`` route. ``id`` is the Django pk; ``org`` is the
    org name; ``state`` carries the primary contact for the L0 "WHO" line and
    the activity timeline. The card is then annotated (days_since_touch,
    quintile_dots) exactly like the old agent-service dicts."""
    contact = thread.primary_contact
    # Map the CRM stage onto the pipeline column key when one applies (else keep
    # the raw stage so a literal column-key stage still buckets correctly).
    column = _CRM_STAGE_TO_COLUMN.get(thread.stage, thread.stage)
    owner = thread.owner if thread.owner_id else None
    card = {
        "id": str(thread.id),
        "org": thread.org.name if thread.org_id else "",
        "stage": column,
        "stage_raw": thread.stage,
        "track": thread.track,
        # Owner is surfaced ONLY on the Team (console) board's Owner badge — the
        # principal (Joseph) board omits it (everything is his lens). Joseph's
        # templates simply don't render this field.
        "owner_id": str(thread.owner_id) if thread.owner_id else "",
        "owner_name": (owner.name or owner.email) if owner else "",
        "traffic_light": thread.traffic_light,
        "quintile": thread.quintile,
        "score": thread.score,
        "next_action": thread.next_action,
        "dossier_id": thread.dossier_id,
        "last_touch_at": thread.last_touch.isoformat() if thread.last_touch else None,
        "state": {
            "contact_name": contact.full_name if contact else "",
            "contact_role": contact.role if contact else "",
        },
    }
    return _annotate_thread(card)


def _crm_threads(*, owner=None, traffic_light=None, track=None):
    """Local CRM OutreachThread queryset (the canonical source), newest first,
    with its org + primary contact + owner pre-fetched. Optional
    owner/traffic_light/track filters mirror the old ``readers.list_threads``
    filters (track powers the Team board's track chips)."""
    from apps.crm.models import OutreachThread

    qs = (
        OutreachThread.objects.select_related("org", "primary_contact", "owner")
        .order_by("-updated_at")
    )
    if traffic_light:
        qs = qs.filter(traffic_light=traffic_light)
    if owner is not None:
        qs = qs.filter(owner=owner)
    if track:
        qs = qs.filter(track=track)
    return qs


def _crm_thread_by_id(thread_id):
    """Resolve a single CRM OutreachThread by its Django (UUID) pk, tolerating a
    non-UUID id (e.g. a legacy agent thread id) → ``None`` rather than a 500."""
    from django.core.exceptions import ValidationError

    from apps.crm.models import OutreachThread

    try:
        return (
            OutreachThread.objects.select_related("org", "primary_contact")
            .filter(pk=thread_id)
            .first()
        )
    except (ValueError, ValidationError):
        return None


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


def _build_pipeline_columns(threads: list[dict]) -> list[dict]:
    """Bucket annotated thread cards into the ordered stage columns + a catch-all.

    The single source of truth for the kanban column structure, shared by BOTH
    the Joseph board and the operator console board so they render identical
    columns. Threads are bucketed by their display ``stage`` (already mapped from
    the CRM Stage by ``_crm_thread_card``) into the five canonical columns
    (Discover → Committed) in order; an unrecognised stage falls into the
    catch-all "Other" tail (appended only when it has cards) so nothing silently
    disappears. Returns ``[{key, label, threads, count}, ...]``.
    """
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
    return columns


@login_required
def pipeline(request):
    """Joseph's principal "My pipeline" board — a traffic-light kanban by stage.

    This is the principal lens (vs the console's "Team pipeline"): the cards carry
    NO Owner badge because the whole board is his to read. Threads are local
    ``apps.crm.OutreachThread`` rows (the CRM is canonical — the strangler step),
    bucketed into the five ordered stage columns (Discover → Committed) with a
    catch-all so an unrecognised stage is never silently dropped. Each card shows
    the org, a traffic-light dot, the quintile and the next action, and links into
    the thread drawer. No agent-service read — an empty DB just renders empty
    columns, never a 500.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    threads = [_crm_thread_card(t) for t in _crm_threads()]
    columns = _build_pipeline_columns(threads)
    return render(request, "joseph/pipeline.html", {"columns": columns})


@login_required
def briefs(request):
    """Index of threads whose L0 brief Joseph can open — the bottom-nav "Brief"
    destination (a thread-less /joseph/brief/ has no card to show). Reads local
    CRM threads (the canonical source), newest first; each row links to its brief
    card. An empty DB → an empty list, never a 500.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")
    threads = [_crm_thread_card(t) for t in _crm_threads()]
    return render(request, "joseph/briefs.html", {"threads": threads})


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

    The thread is a local ``apps.crm.OutreachThread`` (the CRM is canonical — the
    strangler step), resolved by its Django pk. A header (org + stage + score +
    traffic-light) with actions (Request deck / Capture → stubs, Escalate →
    creates a notification) over six HTMX-swappable tabs: Brief / Timeline /
    Intelligence / Tasks / Deck / Sequence. Brief reuses the L0 card mapped from
    the Django thread + its dossier (``readers.get_dossier(dossier_id)``);
    Intelligence pulls the org's wiki page + org-filtered news; Tasks/Timeline
    read the CRM Activity/Task log; Deck/Sequence are present-but-stubbed.

    A full GET renders the shell (defaulting to the Brief tab); an ``HX-Request``
    with ``?tab=`` returns only that tab's partial (CSP-safe ``hx-get``). The
    dossier/wiki/news reads still degrade to a safe default when the agent-service
    is down — the drawer renders an empty state, never a 500.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    tab = (request.GET.get("tab") or "brief").lower()
    if tab not in _DRAWER_TAB_KEYS:
        tab = "brief"

    crm_thread = _crm_thread_by_id(thread_id)
    # Adapt the CRM row into the dict shape the drawer template renders (a missing
    # thread degrades to an empty header rather than a 404 — never a 500).
    thread = _crm_thread_card(crm_thread) if crm_thread else {}
    context = {
        "thread_id": thread_id,
        "thread": thread,
        "crm_thread": crm_thread,
        "tab": tab,
        "tabs": _DRAWER_TABS,
    }
    context.update(_drawer_tab_context(tab, thread_id, thread, crm_thread))

    # HTMX tab switch → swap only the tab partial; a full GET renders the shell.
    if getattr(request, "htmx", False):
        return render(request, f"joseph/_drawer_tabs/{tab}.html", context)
    return render(request, "joseph/thread_drawer.html", context)


def _drawer_tab_context(tab: str, thread_id: str, thread: dict, crm_thread=None) -> dict:
    """Compose the per-tab context (only the active tab does any work)."""
    if tab == "brief":
        return {"card": JosephIntelligence().brief(crm_thread or thread_id, "l0")}
    if tab == "timeline":
        # The append-only CRM Activity log (newest first via Meta.ordering).
        activities = list(crm_thread.activities.select_related("actor").all()) if crm_thread else []
        return {"activities": activities}
    if tab == "tasks":
        tasks = (
            list(crm_thread.tasks.select_related("owner").order_by("status", "-created_at"))
            if crm_thread else []
        )
        return {"tasks": tasks}
    if tab == "intelligence":
        org = thread.get("org") or ""
        from django.utils.text import slugify

        page = readers.get_page(slugify(org), tier="l1") if org else {}
        return {"org": org, "page": page, "news": readers.news_about(org) if org else []}
    if tab == "sequence":
        # Outreach send form + sequence panel (Phase 2C). Provide the enrolled
        # sequences (+ steps), the available templates, and whether the thread
        # owner has an active mailbox so the send button can disable cleanly.
        if not crm_thread:
            return {"sequences": [], "sequence_templates": [], "mailbox_ready": False}
        from apps.outreach.models import Mailbox, Sequence, SequenceTemplate

        sequences = list(
            Sequence.objects.filter(thread=crm_thread)
            .select_related("template")
            .prefetch_related("steps")
            .order_by("-created_at")
        )
        mailbox_ready = bool(
            crm_thread.owner_id
            and Mailbox.objects.filter(
                user_id=crm_thread.owner_id, status=Mailbox.Status.ACTIVE
            ).exists()
        )
        return {
            "sequences": sequences,
            "sequence_templates": list(SequenceTemplate.objects.order_by("name")),
            "mailbox_ready": mailbox_ready,
        }
    # deck carries no extra context (stubbed surface).
    return {}


@login_required
@require_POST
def thread_escalate(request, thread_id):
    """Escalate a thread to Joseph's attention by creating an (urgent)
    notification on the intelligence plane. Degrades quietly when the service is
    down (the reader swallows AgentClientError → empty dict)."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")
    crm_thread = _crm_thread_by_id(thread_id)
    org = (crm_thread.org.name if crm_thread and crm_thread.org_id else None) or thread_id
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


@require_POST
def calendar_link(request, google_event_id):
    """Confirm a calendar event ↔ thread linkage by hand (TB.3).

    The auto-linker only links a confident (≥0.9) match; a mid-band one surfaces
    as a suggestion the principal resolves here, picking the thread by its CRM
    (UUID) pk. Role-gated + CSRF-protected (require_POST); an unknown thread id
    links nothing (and a non-UUID id resolves to ``None`` rather than 500ing).
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    from django.shortcuts import get_object_or_404

    from apps.joseph import linkage
    from apps.joseph.models import CalendarEvent

    event = get_object_or_404(CalendarEvent, google_event_id=google_event_id)
    thread = _crm_thread_by_id(request.POST.get("thread_id"))
    if thread is None:
        messages.error(request, "Couldn't link — that thread no longer exists.")
    else:
        linkage.link_event(event, thread)
        org = thread.org.name if thread.org_id else "thread"
        messages.success(request, f"Linked this meeting to {org}.")
    return redirect("joseph:home")


# The warmth-delta values the quick form offers (mirrors ExtractedMeeting.WarmthDelta).
_WARMTH_DELTAS = [
    ("warmer", "Warmer"),
    ("same", "About the same"),
    ("cooler", "Cooler"),
]


def _capture_event(request, thread):
    """Resolve the optional CalendarEvent a capture is for, scoped to ``thread``.

    The capture forms carry the meeting's ``google_event_id`` so a voice/form/
    defer post can flip the right event's ``capture_status``. A missing/unknown
    id (a hand-typed capture with no linked event) resolves to ``None`` so the
    capture still records — it just doesn't move any calendar state."""
    from apps.joseph.models import CalendarEvent

    gid = (request.POST.get("google_event_id") or "").strip()
    if not gid:
        return None
    return (
        CalendarEvent.objects.filter(
            google_event_id=gid, linked_thread_id=str(thread.id)
        ).first()
    )


@login_required
def capture(request, thread_id):
    """The post-meeting capture surface — Joseph's "I'm going in" follow-up.

    One screen, three paths: record a **voice** note (multipart upload →
    ``VoiceNote`` → async extraction, Task 5), fill a **quick form** (five
    fields: commitments / next step / due date / warmth delta / share toggle →
    a pending ``ExtractedMeeting`` of items, no transcription), or **defer**
    (re-prompt in 2h + a backstop escalation if it rots). The thread is a local
    CRM ``OutreachThread`` (the CRM is canonical); a ``?event=`` carries the
    linked meeting's ``google_event_id`` through so the post can mark it
    captured. Gated by ``_can_access_joseph``; CSP-safe (POST forms + Alpine).
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    crm_thread = _crm_thread_by_id(thread_id)
    google_event_id = (request.GET.get("event") or "").strip()
    return render(
        request,
        "joseph/capture.html",
        {
            "thread_id": thread_id,
            "thread": _crm_thread_card(crm_thread) if crm_thread else {},
            "google_event_id": google_event_id,
            "warmth_deltas": _WARMTH_DELTAS,
            "is_mobile": _is_mobile(request),
        },
    )


@login_required
@require_POST
def capture_voice(request, thread_id):
    """Voice path — persist the uploaded recording then enqueue extraction.

    Writes the audio to a ``VoiceNote`` (status ``uploaded``) via the project's
    configured FileField storage (R2 in prod, FS in dev/test — no bespoke upload
    code), marks the linked event ``captured``, and enqueues the async
    transcription→extraction pipeline (Task 5) with the new note's id. Role-gated
    + CSRF (require_POST)."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    from apps.joseph import capture as capture_logic
    from apps.joseph.models import VoiceNote

    crm_thread = _crm_thread_by_id(thread_id)
    if crm_thread is None:
        messages.error(request, "Couldn't capture — that thread no longer exists.")
        return redirect("joseph:home")

    audio = request.FILES.get("audio")
    if not audio:
        messages.error(request, "No recording received — try again.")
        return redirect("joseph:capture", thread_id=thread_id)

    event = _capture_event(request, crm_thread)
    note = VoiceNote.objects.create(
        thread=crm_thread,
        calendar_event=event,
        file=audio,
        status=VoiceNote.Status.UPLOADED,
        created_by=request.user,
    )
    capture_logic.mark_captured(event)
    # Hand off to the async pipeline (transcription seam → extraction seam → items).
    extract_meeting.delay(str(note.id))

    messages.success(request, "Got it — transcribing your note and pulling out the actions.")
    return redirect("joseph:thread", thread_id=thread_id)


@login_required
@require_POST
def capture_form(request, thread_id):
    """Quick-form path — five fields straight into a pending ExtractedMeeting.

    Commitments / next step / due date / warmth delta / share-toggle map onto
    ``ExtractedItem`` rows directly (no transcription), and the warmth delta is
    stored on the meeting for the confirm-time rescore (Task 6). Marks the linked
    event ``captured``. Role-gated + CSRF (require_POST)."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    from apps.joseph import capture as capture_logic

    crm_thread = _crm_thread_by_id(thread_id)
    if crm_thread is None:
        messages.error(request, "Couldn't capture — that thread no longer exists.")
        return redirect("joseph:home")

    event = _capture_event(request, crm_thread)
    capture_logic.build_form_meeting(
        crm_thread,
        commitments=request.POST.get("commitments", ""),
        next_step=request.POST.get("next_step", ""),
        due_date=request.POST.get("due_date", ""),
        warmth_delta=(request.POST.get("warmth_delta") or "").strip().lower(),
        share=bool(request.POST.get("share")),
    )
    capture_logic.mark_captured(event)

    messages.success(request, "Captured — review the items to route them.")
    return redirect("joseph:thread", thread_id=thread_id)


@login_required
@require_POST
def capture_defer(request, thread_id):
    """Defer path — re-prompt in 2h, with a backstop escalation if it rots.

    Marks the linked event ``deferred`` with a ``defer_until`` 2h out; the beat
    sweep re-prompts then, and ``escalate_deferred_captures`` escalates to the
    thread backstop after 24h if it is still uncaptured. Role-gated + CSRF."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    from apps.joseph import capture as capture_logic

    crm_thread = _crm_thread_by_id(thread_id)
    event = _capture_event(request, crm_thread) if crm_thread else None
    if event is not None:
        capture_logic.defer_capture(event)
        messages.success(request, "Deferred — I'll remind you in a couple of hours.")
    else:
        messages.error(request, "Couldn't defer — no linked meeting to defer.")
    return redirect("joseph:home")


def _extracted_meeting(meeting_id):
    """Resolve a pending/confirmed ExtractedMeeting by its (UUID) pk + thread,
    tolerating a non-UUID id → ``None`` rather than a 500."""
    from django.core.exceptions import ValidationError

    from apps.joseph.models import ExtractedMeeting

    try:
        return (
            ExtractedMeeting.objects.select_related("thread", "thread__org")
            .filter(pk=meeting_id)
            .first()
        )
    except (ValueError, ValidationError):
        return None


@login_required
def meeting_confirm(request, extracted_meeting_id):
    """One-tap meeting confirm + routing (TB.4) — Joseph reviews then routes.

    GET lists the meeting's ``ExtractedItem`` lines (accept/edit/dismiss + a
    bulk-accept). POST walks them: an accepted item is routed by its ``kind``
    (``routing.apply_item``) into Activities/Tasks/intake/wiki, a dismissed one
    logs an "outcome logged" note (``routing.dismiss_item``), the meeting's
    warmth delta folds into the thread (``routing.apply_warmth`` → rescore), and
    the meeting is marked ``confirmed``. The thread is the canonical CRM
    OutreachThread. Gated by ``_can_access_joseph``; CSP-safe (POST forms)."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Joseph's principal surface is not available for your role.")

    meeting = _extracted_meeting(extracted_meeting_id)
    if meeting is None:
        from django.http import Http404

        raise Http404("No such meeting.")

    if request.method == "POST":
        return _route_confirmed_meeting(request, meeting)

    return render(
        request,
        "joseph/meeting_confirm.html",
        {
            "meeting": meeting,
            "thread": _crm_thread_card(meeting.thread) if meeting.thread_id else {},
            "thread_id": str(meeting.thread_id),
            "items": list(meeting.items.all()),
            "is_mobile": _is_mobile(request),
        },
    )


def _route_confirmed_meeting(request, meeting):
    """Walk the posted accept/dismiss actions, route each item, apply warmth,
    mark the meeting confirmed. ``bulk=accept`` accepts every item; otherwise an
    ``action_<item_id>`` field (``accept``/``dismiss``) picks per item (a missing
    one defaults to accept so a one-tap confirm routes everything)."""
    from apps.joseph import routing

    workspace = getattr(request, "workspace", None)
    bulk = (request.POST.get("bulk") or "").strip().lower() == "accept"

    for item in meeting.items.all():
        item._by_user = request.user  # actor hint for note routing
        action = (request.POST.get(f"action_{item.id}") or "").strip().lower()
        if not bulk and action == "dismiss":
            routing.dismiss_item(item)
        else:
            # bulk-accept, an explicit accept, or no per-item choice → accept.
            routing.apply_item(item, by_user=request.user, workspace=workspace)

    routing.apply_warmth(meeting)

    from apps.joseph.models import ExtractedMeeting

    meeting.status = ExtractedMeeting.Status.CONFIRMED
    meeting.save(update_fields=["status", "updated_at"])

    messages.success(request, "Confirmed — the meeting's actions are routed.")
    return redirect("joseph:thread", thread_id=str(meeting.thread_id))


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
