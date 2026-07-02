"""AI Studio chat views — the conversational content generator.

A workspace-scoped chat where a user converses with the drafting brain
(``apps.composer.generation``) to produce a grounded, voiced, de-slopped master
piece. Each assistant turn can carry a reusable draft; "Use this" hands the
draft to the campaign composer to publish across channels.

The authoritative publish gate still runs at dispatch; posts created here are
human-initiated so their PlatformPosts set ``gate_bypassed=True``.
"""
from __future__ import annotations

import json
import logging

from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST

from apps.social_accounts.models import SocialAccount

from . import generation
from .models import ContentChat, ContentChatMessage, PlatformPost, Post
from .views import _get_workspace

logger = logging.getLogger(__name__)

_VOICES = [
    {"key": "joseph", "label": "Joseph's voice"},
    {"key": "company", "label": "Company voice"},
]


def _connected_accounts(workspace):
    """Connected social accounts for the workspace, ghost-first then A-Z."""
    accounts = list(
        SocialAccount.objects.for_workspace(workspace.id).filter(
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
    )
    accounts.sort(key=lambda a: (a.platform != "ghost", a.platform, a.account_name or ""))
    return accounts


def _accounts_meta(accounts):
    """{str(id): {name, platform, platform_label, limit, is_ghost}} for json_script."""
    meta = {}
    for acc in accounts:
        meta[str(acc.id)] = {
            "name": acc.account_name or acc.account_handle or acc.get_platform_display(),
            "platform": acc.platform,
            "platform_label": acc.get_platform_display(),
            "limit": acc.char_limit,
            "is_ghost": acc.platform == "ghost",
            "logo_display_url": acc.logo_display_url,
        }
    return meta


def _resolve_channels(workspace, channels_csv):
    """Resolve a csv of account ids (empty = all connected) → list of accounts,
    preserving ghost-first ordering and dropping unknown/disconnected ids."""
    connected = _connected_accounts(workspace)
    ids = [s.strip() for s in (channels_csv or "").split(",") if s.strip()]
    if not ids:
        return connected
    by_id = {str(a.id): a for a in connected}
    return [by_id[i] for i in ids if i in by_id]


@login_required
def studio(request, workspace_id, chat_id=None):
    """List the workspace's chats + render the active chat (or a blank studio)."""
    workspace = _get_workspace(request, workspace_id)

    chats = ContentChat.objects.for_workspace(workspace.id).order_by("-updated_at")

    chat = None
    messages = []
    if chat_id is not None:
        chat = get_object_or_404(
            ContentChat, id=chat_id, workspace=workspace,
        )
        messages = list(chat.messages.all())

    accounts = _connected_accounts(workspace)

    context = {
        "workspace": workspace,
        "chats": chats,
        "chat": chat,
        "messages": messages,
        "social_accounts": accounts,
        "accounts_meta": _accounts_meta(accounts),
        "voices": _VOICES,
    }
    return render(request, "composer/ai_studio.html", context)


@login_required
@require_POST
def chat_send(request, workspace_id):
    """Handle a chat turn (htmx): persist the user message, generate a reply +
    draft, persist the assistant message, and render the turn partial."""
    workspace = _get_workspace(request, workspace_id)

    message = (request.POST.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "Message is required."}, status=400)

    voice = (request.POST.get("voice") or "joseph").strip() or "joseph"
    if voice not in {v["key"] for v in _VOICES}:
        voice = "joseph"
    channels_csv = request.POST.get("channels") or ""
    chat_id = (request.POST.get("chat_id") or "").strip()

    # Get-or-create the chat (workspace + user scoped).
    chat = None
    if chat_id:
        chat = ContentChat.objects.for_workspace(workspace.id).filter(
            id=chat_id, user=request.user,
        ).first()
    if chat is None:
        chat = ContentChat.objects.create(
            workspace=workspace,
            user=request.user,
            title=message[:60],
            voice=voice,
        )

    # Persist the user's turn.
    ContentChatMessage.objects.create(chat=chat, role="user", content=message)

    # Build channel meta for the reply copy + prior-turn history for context.
    channels_meta = [
        {"platform_label": acc.get_platform_display(), "platform": acc.platform, "id": str(acc.id)}
        for acc in _resolve_channels(workspace, channels_csv)
    ]
    history = [
        {"role": m.role, "content": m.content}
        for m in chat.messages.all()
        if m.content
    ]

    # generate_content NEVER raises.
    result = generation.generate_content(
        workspace=workspace,
        user_prompt=message,
        voice=voice,
        channels=channels_meta,
        history=history,
    )

    assistant_msg = None
    try:
        assistant_msg = ContentChatMessage.objects.create(
            chat=chat,
            role="assistant",
            content=result.get("reply") or "",
            draft={
                "title": result.get("title") or "",
                "master_html": result.get("master_html") or "",
                "sources": result.get("sources") or [],
            },
        )
        chat.save(update_fields=["updated_at"])
    except Exception:  # pragma: no cover - defensive DB guard
        logger.exception("chat_send: failed to persist assistant message")
        if assistant_msg is None:
            # Render an in-memory message so the UI still shows the reply.
            assistant_msg = ContentChatMessage(
                chat=chat,
                role="assistant",
                content=result.get("reply") or "",
                draft={
                    "title": result.get("title") or "",
                    "master_html": result.get("master_html") or "",
                    "sources": result.get("sources") or [],
                },
            )

    response = render(
        request,
        "composer/_chat_turn.html",
        {"workspace": workspace, "chat": chat, "user_text": message, "msg": assistant_msg},
    )
    response["HX-Trigger"] = json.dumps({
        "chatCreated": {
            "chatId": str(chat.id),
            "url": reverse("composer:chat_detail", kwargs={"workspace_id": workspace.id, "chat_id": chat.id}),
        }
    })
    return response


@login_required
@require_POST
def chat_use(request, workspace_id, chat_id, message_id):
    """Materialise an assistant draft into a Post + PlatformPosts, then redirect
    into the campaign composer to publish across channels."""
    workspace = _get_workspace(request, workspace_id)

    chat = get_object_or_404(ContentChat, id=chat_id, workspace=workspace)
    msg = get_object_or_404(ContentChatMessage, id=message_id, chat=chat)

    draft = msg.draft or {}
    title = (draft.get("title") or "Untitled draft")[:255]
    master_html = draft.get("master_html") or ""
    sources = draft.get("sources") or []

    post = Post.objects.create(
        workspace=workspace,
        author=request.user,
        title=title,
        caption=strip_tags(master_html)[:5000],
        ai_brief={"sources": sources, "assets": [], "guardrails": []},
    )

    # Build PlatformPosts for the connected accounts (channels csv if provided).
    channels_csv = request.POST.get("channels") or ""
    for acc in _resolve_channels(workspace, channels_csv):
        pp = PlatformPost(
            post=post,
            social_account=acc,
            status="draft",
            gate_bypassed=True,
        )
        if acc.platform == "ghost":
            pp.platform_specific_caption = master_html
            pp.platform_extra = {"ghost_publish_as": "post"}
        else:
            # Leave caption None → campaign composer's Draft-all fills per-channel.
            pp.platform_specific_caption = None
            pp.platform_extra = {}
        pp.save()

    redirect_url = (
        reverse("composer:campaign", kwargs={"workspace_id": workspace.id})
        + f"?post={post.id}"
    )
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = redirect_url
        return response
    return HttpResponseRedirect(redirect_url)


@login_required
def chat_new(request, workspace_id):
    """Redirect to a blank studio (new chat)."""
    _get_workspace(request, workspace_id)  # membership / 403 check
    return redirect("composer:chat", workspace_id=workspace_id)
