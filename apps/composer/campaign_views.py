# apps/composer/campaign_views.py
"""Campaign composer: one master piece -> Ghost article + per-channel captions.

Two endpoints (contract shared with the campaign.html frontend):

- ``campaign``       GET  -> renders composer/campaign.html
- ``campaign_draft`` POST -> JSON AI drafting endpoint. Asks HERALD (the
  existing agent-service drafting seam, same one apps/content_intake's
  herald_bridge uses) for a per-channel caption; ALWAYS falls back to a
  deterministic caption on any failure. Never 500s on AI failure.

Every non-ghost caption contains the literal token ``[NEXUS BRIEF LINK]``
which is resolved AT DISPATCH (after the gate) to the sibling Ghost
PlatformPost's published_url — same pattern as apps/publisher/utm.apply_utm.
"""
from __future__ import annotations

import json
import logging
import re

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST

from apps.common.agent_client import agent_get, agent_post
from apps.content_intake.sector_map import map_pillar_to_sector
from apps.social_accounts.models import SocialAccount

from .models import Post
from .views import _get_workspace

logger = logging.getLogger(__name__)

LINK_TOKEN = "[NEXUS BRIEF LINK]"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


@login_required
def campaign(request, workspace_id):
    """Render the campaign composer (new post, or edit via ?post=<uuid>)."""
    workspace = _get_workspace(request, workspace_id)

    social_accounts = list(
        SocialAccount.objects.for_workspace(workspace.id)
        .filter(connection_status=SocialAccount.ConnectionStatus.CONNECTED)
        .order_by("platform", "account_name")
    )
    # ponytail: ghost-first ordering via a stable sort key instead of SQL CASE.
    social_accounts.sort(key=lambda a: a.platform != "ghost")

    post = None
    post_id = request.GET.get("post")
    if post_id:
        try:
            post = Post.objects.get(id=post_id, workspace=workspace)
        except (Post.DoesNotExist, ValidationError, ValueError):
            raise Http404("Post not found.")

    accounts_meta = {
        str(acc.id): {
            "name": acc.account_name or acc.account_handle,
            "platform": acc.platform,
            "platform_label": acc.get_platform_display(),
            "limit": acc.char_limit,
            "is_ghost": acc.platform == "ghost",
        }
        for acc in social_accounts
    }

    overrides_map = {}
    if post:
        overrides_map = {
            str(pp.social_account_id): pp.platform_specific_caption or ""
            for pp in post.platform_posts.all()
        }

    return render(
        request,
        "composer/campaign.html",
        {
            "workspace": workspace,
            "social_accounts": social_accounts,
            "post": post,
            "accounts_meta": accounts_meta,
            "overrides_map": overrides_map,
        },
    )


# ---------------------------------------------------------------------------
# AI drafting endpoint
# ---------------------------------------------------------------------------


def _plain_text(master_html: str) -> str:
    """Master HTML -> whitespace-normalised plain text."""
    return re.sub(r"\s+", " ", strip_tags(master_html or "")).strip()


# A resolved Nexus Brief URL (+UTM params, injected post-gate at dispatch) is
# far longer than the 18-char token. Budget for it here so the DISPATCHED
# caption still fits the platform limit after resolve_nexus_link swaps it in
# — matters most for tight-limit channels (Bluesky 300, Threads 500).
_URL_RESERVE = 130


def _fit_with_token(caption: str, limit: int) -> str:
    """Ensure the caption contains LINK_TOKEN and — once the token is swapped
    for the (longer) live article URL at dispatch — still fits within limit."""
    caption = (caption or "").strip()
    if LINK_TOKEN not in caption:
        caption = f"{caption}\n\nFull piece: {LINK_TOKEN}" if caption else f"Full piece: {LINK_TOKEN}"
    headroom = max(len(LINK_TOKEN), _URL_RESERVE)
    # Project the length after the token becomes a full URL.
    if len(caption) - len(LINK_TOKEN) + headroom <= limit:
        return caption
    # Over budget: keep the text before the token, force a clean token tail.
    # ponytail: may cut mid-word; every platform limit (>=280) dwarfs the tail.
    head = caption.split(LINK_TOKEN, 1)[0].rstrip(" \n:-")
    tail = f"\n\n{LINK_TOKEN}"
    room = limit - len(tail) - (headroom - len(LINK_TOKEN))
    if room <= 0:  # pathological (limit < ~130); keep the token anyway
        return LINK_TOKEN
    return head[:room].rstrip() + tail


def _fallback_caption(title: str, master_text: str, limit: int) -> str:
    """Deterministic caption: title + first 2 sentences + token tail."""
    sentences = re.split(r"(?<=[.!?])\s+", master_text)
    lead = " ".join(s for s in sentences[:2] if s).strip()
    base = f"{title.strip()}\n\n{lead}".strip() if title.strip() else lead
    return _fit_with_token(base, limit)


def _herald_brief(title: str, master_text: str, meta: dict, brief: dict) -> str:
    """Render the campaign brief into a HERALD prompt for one channel."""
    lines = [
        f"Write ONE {meta['platform_label']} post (hard maximum {meta['limit']} characters) "
        f"promoting the article below, in Joseph's professional voice.",
        f"It MUST contain the literal placeholder token {LINK_TOKEN} exactly once, "
        f"where the link to the full article belongs.",
        f"TITLE: {title}",
        f"ARTICLE: {master_text[:4000]}",
    ]
    guardrails = [g for g in (brief.get("guardrails") or []) if isinstance(g, str) and g.strip()]
    if guardrails:
        lines.append("GUARDRAILS (obey strictly):")
        lines.extend(f"- {g.strip()}" for g in guardrails)
    assets = [a for a in (brief.get("assets") or []) if isinstance(a, dict) and a.get("url")]
    if assets:
        lines.append(
            "SUPPORTING ASSETS: "
            + "; ".join(f"{a.get('label') or a['url']} ({a['url']})" for a in assets)
        )
    return "\n".join(lines)


def _herald_caption(sector: str, herald_brief: str, platform: str) -> str:
    """One HERALD draft for one channel; returns "" when unusable.

    ponytail: reuses the existing /agents/herald/draft seam (it persists a
    ContentItem on the agent-service and runs its own gate check) then reads
    the body back via /content/items/<id>. Two calls x 10s client timeout
    keeps us <=20s per channel; ANY failure means the deterministic fallback.
    """
    result = agent_post(
        "/agents/herald/draft",
        {"sector": sector, "brief": herald_brief, "count": 1,
         "voice_user": "joseph", "channel": platform},
    )
    proposals = (result or {}).get("proposals") or []
    if not proposals or not isinstance(proposals[0], dict) or not proposals[0].get("id"):
        return ""
    item = agent_get(f"/content/items/{proposals[0]['id']}")
    return str((item or {}).get("body") or "")


@login_required
@require_POST
def campaign_draft(request, workspace_id):
    """AI-draft per-channel caption variants for the campaign composer.

    Request/response JSON per the shared contract. Ghost accounts get no
    variant (their caption IS the master body). Never 500s on AI failure —
    the deterministic fallback always produces a valid caption.
    """
    workspace = _get_workspace(request, workspace_id)

    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid JSON"}, status=400)

    title = str(payload.get("title") or "")
    master_text = _plain_text(str(payload.get("master_html") or ""))
    brief = payload.get("brief") if isinstance(payload.get("brief"), dict) else {}
    requested = [str(a) for a in (payload.get("accounts") or [])]
    only_account = payload.get("only_account")
    if only_account:
        requested = [str(only_account)]

    accounts = SocialAccount.objects.for_workspace(workspace.id).filter(
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    by_id = {str(acc.id): acc for acc in accounts}

    sector = map_pillar_to_sector(f"{title} {master_text[:500]}")
    variants: dict[str, dict] = {}
    ai_used = False
    ai_failed = False

    for acc_id in requested:
        acc = by_id.get(acc_id)
        if acc is None or acc.platform == "ghost":
            continue  # unknown/foreign accounts skipped; ghost = master body
        meta = {"platform_label": acc.get_platform_display(), "limit": acc.char_limit}
        caption = ""
        try:
            caption = _herald_caption(
                sector, _herald_brief(title, master_text, meta, brief), acc.platform
            )
        except Exception:
            logger.warning(
                "campaign_draft: HERALD failed for account=%s; using fallback",
                acc_id, exc_info=True,
            )
        if caption:
            ai_used = True
            variants[acc_id] = {"caption": _fit_with_token(caption, acc.char_limit)}
        else:
            ai_failed = True
            variants[acc_id] = {"caption": _fallback_caption(title, master_text, acc.char_limit)}

    # ponytail: single top-level source per contract — report "herald" only
    # when every variant came from the AI.
    source = "herald" if ai_used and not ai_failed else "fallback"
    return JsonResponse({"source": source, "variants": variants})
