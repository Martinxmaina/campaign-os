# apps/composer/campaign_views.py
"""Campaign composer: one master piece -> Ghost article + per-channel captions.

Two endpoints (contract shared with the campaign.html frontend):

- ``campaign``       GET  -> renders composer/campaign.html
- ``campaign_draft`` POST -> JSON AI drafting endpoint. Routes per-channel
  drafting through ``apps.composer.generation.draft_caption`` (DeepSeek-first,
  with HERALD + a deterministic template baked in as fallback); ALWAYS returns
  a valid caption. Never 500s on AI failure.

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

from apps.social_accounts.models import SocialAccount

from . import generation
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

    voice = payload.get("voice") or "joseph"
    # ponytail: retrieve grounding ONCE for the whole campaign, not per-channel.
    try:
        grounding = generation.build_grounding(workspace, f"{title} {master_text[:400]}")
    except Exception:
        logger.warning("campaign_draft: build_grounding failed", exc_info=True)
        grounding = None

    variants: dict[str, dict] = {}
    per_source: list[str] = []

    for acc_id in requested:
        acc = by_id.get(acc_id)
        if acc is None or acc.platform == "ghost":
            continue  # unknown/foreign accounts skipped; ghost = master body
        try:
            caption, src = generation.draft_caption(
                workspace=workspace,
                title=title,
                master_text=master_text,
                platform=acc.platform,
                platform_label=acc.get_platform_display(),
                char_limit=acc.char_limit,
                brief=brief,
                voice=voice,
                grounding=grounding,
            )
        except Exception:
            # generation.draft_caption never raises, but stay defensive: a
            # deterministic caption keeps the endpoint from ever 500ing.
            logger.warning(
                "campaign_draft: draft_caption failed for account=%s", acc_id, exc_info=True,
            )
            caption, src = generation._fallback_caption(title, master_text, acc.char_limit), "fallback"
        variants[acc_id] = {"caption": caption}
        per_source.append(src)

    # Single top-level source per contract: "deepseek" only when every variant
    # came from DeepSeek; "herald" when any channel used the HERALD fallback;
    # otherwise "fallback".
    if per_source and all(s == "deepseek" for s in per_source):
        source = "deepseek"
    elif "herald" in per_source:
        source = "herald"
    else:
        source = "fallback"
    return JsonResponse({"source": source, "variants": variants})
