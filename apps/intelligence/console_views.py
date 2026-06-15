"""Agent-service-backed console: pipeline, notifications, brain (Slice G')."""
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.common.agent_client import agent_post
from apps.common.safe import safe_get
from apps.content_intake.sector_map import map_pillar_to_sector

logger = logging.getLogger(__name__)


@login_required
def pipeline(request):
    """Operator deal-flow board — canonical Django threads, drag-to-restage.

    Repointed off the stale agent-service ``/threads`` read: the console now
    queries ``apps.crm.OutreachThread`` (the canonical CRM, the strangler step)
    and buckets the cards into the SAME ordered stage columns Joseph's board uses
    (Discover → Committed + a catch-all "Other"), so both pipelines render one
    source of truth. Cards drag between columns and POST the move to the single
    shared ``crm:thread-set-stage`` endpoint (Task 2). Role-gated by
    ``_can_manage_crm`` (the CRM gate ``set_stage`` itself enforces — a viewer who
    can't restage shouldn't see the board). No agent-service call; an empty DB
    renders empty columns, never a 500.
    """
    from apps.crm.views_import import _can_manage_crm
    from apps.joseph.views import _build_pipeline_columns, _crm_thread_card, _crm_threads

    if not _can_manage_crm(request):
        return HttpResponseForbidden("The pipeline is not available for your role.")

    threads = [_crm_thread_card(t) for t in _crm_threads()]
    columns = _build_pipeline_columns(threads)
    return render(request, "console/pipeline.html", {"columns": columns})


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


# --- Agent-brain Learning Log + diff-review (Loop 2, Task 5) --------------------
#
# The agent-service Evaluator (Tasks 3/4) proposes evidence-backed playbook diffs
# that have already passed the eval suite (a compliance failure auto-rejects). This
# console renders the weekly Learning memos + the proposed diffs and drives human
# approval against the lead-gated ``/brain/*`` API. NO code path here writes a
# constitution or rubric — those are frozen Level-2 artifacts; the console only
# applies/rejects diffs the brain already produced. Reads degrade to an empty state
# when agent-service is down (never 500); mutations are owner/admin gated.


def _can_review_brain(request) -> bool:
    """Gate for the Learning console + diff approval.

    Playbook diffs change how an agent behaves org-wide, so authentication alone is
    not enough (the same 'any member can touch a sensitive object' gap closed for
    the brand voice). Gate on staff (superuser escape hatch) or an owner/admin
    workspace role (reusing the membership RBACMiddleware already resolved) — the
    Django mirror of the agent-service ``require_role('lead')`` on mutations.
    """
    if getattr(request.user, "is_staff", False):
        return True
    m = getattr(request, "workspace_membership", None)
    return bool(m and m.workspace_role in ("owner", "admin"))


@login_required
def learning_log(request):
    """Weekly Evaluator Learning memos + per-agent proposed-diff counts."""
    if not _can_review_brain(request):
        return HttpResponseForbidden("The Learning Log is not available for your role.")
    raw = safe_get("/brain/learnings", default=None)
    learnings = (raw or {}).get("learnings", []) if isinstance(raw, dict) else []
    return render(request, "console/learning_log.html",
                  {"learnings": learnings, "down": raw is None})


@login_required
def diff_list(request):
    """Proposed playbook diffs awaiting review."""
    if not _can_review_brain(request):
        return HttpResponseForbidden("The diff review is not available for your role.")
    raw = safe_get("/brain/proposals", default=None)
    proposals = (raw or {}).get("proposals", []) if isinstance(raw, dict) else []
    return render(request, "console/diff_list.html",
                  {"proposals": proposals, "down": raw is None})


@login_required
def diff_detail(request, proposal_id):
    """Side-by-side diff + evidence episodes + eval-run result + Approve/Reject."""
    if not _can_review_brain(request):
        return HttpResponseForbidden("The diff review is not available for your role.")
    raw = safe_get("/brain/proposals", default=None)
    if raw is None:
        return render(request, "console/diff_detail.html", {"down": True, "proposal": None})
    proposals = (raw or {}).get("proposals", []) if isinstance(raw, dict) else []
    proposal = next((p for p in proposals if str(p.get("id")) == str(proposal_id)), None)
    eval_run = None
    if proposal and proposal.get("eval_run_id"):
        er = safe_get(f"/brain/eval-runs/{proposal['eval_run_id']}", default=None)
        eval_run = er if isinstance(er, dict) else None
    return render(request, "console/diff_detail.html",
                  {"proposal": proposal, "eval_run": eval_run, "down": False})


@login_required
@require_POST
def diff_apply(request, proposal_id):
    """Approve a proposed diff → it goes live (lead-gated; agent-down → graceful)."""
    if not _can_review_brain(request):
        return HttpResponseForbidden("You are not authorized to approve playbook diffs.")
    try:
        agent_post(f"/brain/proposals/{proposal_id}/apply", {})
    except Exception:
        logger.warning("diff_apply: agent_post failed", exc_info=True)
    return redirect("console:diff-list")


@login_required
@require_POST
def diff_reject(request, proposal_id):
    """Reject a proposed diff → no version goes live (lead-gated; agent-down → graceful)."""
    if not _can_review_brain(request):
        return HttpResponseForbidden("You are not authorized to reject playbook diffs.")
    try:
        agent_post(f"/brain/proposals/{proposal_id}/reject", {})
    except Exception:
        logger.warning("diff_reject: agent_post failed", exc_info=True)
    return redirect("console:diff-list")


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
