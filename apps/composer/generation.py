"""Content generation service — DeepSeek-first, grounded, voiced, de-slopped.

The central drafting brain for BOTH the AI Studio chat and the campaign
per-channel drafts. Generation goes DIRECTLY to DeepSeek
(``apps.common.deepseek_client``) instead of the HERALD agent; when DeepSeek
isn't configured it falls back to the agent-service HERALD draft, then to a
deterministic template. Every draft is run through ``apps.composer.deslop`` and
— for social channels — carries the ``[NEXUS BRIEF LINK]`` token that
``apps.publisher.links.resolve_nexus_link`` swaps for the live article URL at
dispatch.

Grounding is pulled from:
- the knowledge wiki           → apps.joseph.readers.search_pages
- best-performing past posts   → apps.analytics.services.all_posts_for
- the selected voice profile   → agent-service /voice/<name> or a baked-in one

The authoritative publish gate still runs at dispatch — this only drafts, so
going direct to DeepSeek here is safe.
"""
from __future__ import annotations

import logging
import re

from django.utils.html import strip_tags

from apps.common import deepseek_client
from apps.composer.deslop import deslop, deslop_html

logger = logging.getLogger(__name__)

LINK_TOKEN = "[NEXUS BRIEF LINK]"
# A resolved Nexus Brief URL (+UTM, injected post-gate at dispatch) is far
# longer than the token; budget for it so tight-limit channels still fit.
_URL_RESERVE = 130

# Standing AfCEN facts the generator must never get wrong (from the brand
# guardrails). Included in every system prompt as ground truth.
_HOUSE_FACTS = (
    "HOUSE FACTS (never contradict): AfCEN is a PARTNER and convener, NOT a "
    "capital controller or fund manager. Write 'AI 10Bn' WITHOUT a '$' sign. "
    "The AI Hub was founded by ITALY (G7 presidency) and is co-led with UNDP; "
    "AfDB is credited only in the AI 10Bn financing context, not as the Hub's "
    "founder. WAIIS is the AfCEN + PI-CREF co-secretariat. Mozambique is a "
    "'data embassy'; West Africa / Sierra Leone is a 'digital embassy'."
)

# Baked-in company voice — used for the "company" voice option and as a floor
# when the agent-service voice profile is unavailable.
_COMPANY_VOICE = {
    "tone": (
        "Confident, credible, plain-spoken. Africa-forward and partnership-"
        "minded. Concrete over grandiose. Never salesy, never hype."
    ),
    "banned_phrases": [
        "game-changer", "revolutionary", "unlock", "delve", "in today's world",
        "leverage", "cutting-edge", "seamless", "robust", "synergy",
    ],
    "signature_moves": [
        "Lead with the concrete stakes for Africa.",
        "Name real institutions and programmes precisely.",
        "Short sentences. One idea per line.",
    ],
}


# ---------------------------------------------------------------------------
# Token / length helpers (shared with the campaign composer)
# ---------------------------------------------------------------------------


def fit_with_token(caption: str, limit: int) -> str:
    """Ensure caption contains LINK_TOKEN and — once the token becomes a full
    URL at dispatch — still fits within limit."""
    caption = (caption or "").strip()
    if LINK_TOKEN not in caption:
        caption = f"{caption}\n\nFull piece: {LINK_TOKEN}" if caption else f"Full piece: {LINK_TOKEN}"
    headroom = max(len(LINK_TOKEN), _URL_RESERVE)
    if len(caption) - len(LINK_TOKEN) + headroom <= limit:
        return caption
    head = caption.split(LINK_TOKEN, 1)[0].rstrip(" \n:-")
    tail = f"\n\n{LINK_TOKEN}"
    room = limit - len(tail) - (headroom - len(LINK_TOKEN))
    if room <= 0:
        return LINK_TOKEN
    return head[:room].rstrip() + tail


def _plain_text(html: str) -> str:
    return re.sub(r"\s+", " ", strip_tags(html or "")).strip()


def _fallback_caption(title: str, master_text: str, limit: int) -> str:
    """Deterministic caption: title + first 2 sentences + token tail."""
    sentences = re.split(r"(?<=[.!?])\s+", master_text or "")
    lead = " ".join(s for s in sentences[:2] if s).strip()
    base = f"{title.strip()}\n\n{lead}".strip() if (title or "").strip() else lead
    return fit_with_token(deslop(base), limit)


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------


def fetch_voice(voice: str = "joseph") -> dict:
    """Return the voice profile dict for the requested voice.

    "company" → the baked-in AfCEN voice. Anything else (default "joseph") →
    the agent-service profile at /voice/<name>, falling back to the company
    voice if the service is unavailable.
    """
    if voice == "company":
        return dict(_COMPANY_VOICE)
    try:
        from apps.common.agent_client import agent_get

        data = agent_get(f"/voice/{voice}") or {}
        body = data.get("body") if isinstance(data, dict) else None
        if isinstance(body, dict) and body:
            return body
    except Exception:
        logger.info("fetch_voice: agent-service voice/%s unavailable; using company floor", voice)
    return dict(_COMPANY_VOICE)


def _voice_system(voice_profile: dict, *, channel_label: str = "") -> str:
    """Compose the system prompt from a voice profile + house facts."""
    lines = [
        "You are a senior communications writer for AfCEN (the Africa Centre "
        "for Energy & Nature). You write publish-ready content that sounds like "
        "a sharp human professional — never like an AI.",
        _HOUSE_FACTS,
    ]
    tone = (voice_profile or {}).get("tone")
    if tone:
        lines.append(f"VOICE / TONE: {tone}")
    moves = (voice_profile or {}).get("signature_moves") or []
    if moves:
        lines.append("SIGNATURE MOVES:\n" + "\n".join(f"- {m}" for m in moves if m))
    banned = (voice_profile or {}).get("banned_phrases") or []
    if banned:
        lines.append("BANNED PHRASES (never use): " + ", ".join(str(b) for b in banned if b))
    lines.append(
        "ANTI-SLOP RULES: no em-dashes, no 'delve/tapestry/robust/leverage/"
        "seamless', no 'In today's world', no hedging preambles, no emoji spam, "
        "no exclamation storms. Write plainly and specifically."
    )
    if channel_label:
        lines.append(f"You are writing for: {channel_label}.")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


def build_grounding(workspace, query: str, *, wiki_limit: int = 6, posts_limit: int = 6) -> dict:
    """Retrieve grounding for a query: wiki passages + best-performing posts.

    Never raises — any retrieval failure degrades to empty lists.
    """
    wiki: list[dict] = []
    best_posts: list[dict] = []
    sources: list[str] = []

    try:
        from apps.joseph.readers import search_pages

        for p in (search_pages(q=query, limit=wiki_limit) or [])[:wiki_limit]:
            title = (p.get("title") or p.get("slug") or "").strip()
            body = _plain_text(p.get("body") or p.get("content") or "")
            if body:
                wiki.append({"title": title, "body": body[:1200]})
                if title:
                    sources.append(f"Wiki: {title}")
    except Exception:
        logger.info("build_grounding: wiki search unavailable", exc_info=True)

    try:
        from apps.analytics.services import all_posts_for
        from apps.social_accounts.models import SocialAccount

        accounts = SocialAccount.objects.for_workspace(workspace.id).filter(
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        for acc in accounts:
            try:
                res = all_posts_for(
                    account=acc, days_filter=180, sort_key="reach",
                    sort_dir="desc", page=1, page_size=2,
                )
            except Exception:
                continue
            for row in (res.get("rows") or [])[:2]:
                cap = (row.get("caption") or "").strip()
                if not cap:
                    continue
                stats = row.get("stats") or {}
                metric, value = "", 0
                for k in ("reach", "impressions", "engagement", "likes"):
                    if stats.get(k):
                        metric, value = k, stats[k]
                        break
                best_posts.append({
                    "platform": acc.get_platform_display(),
                    "caption": cap[:400],
                    "metric": metric,
                    "value": value,
                })
    except Exception:
        logger.info("build_grounding: analytics unavailable", exc_info=True)

    # Keep only the strongest few examples across platforms.
    best_posts.sort(key=lambda b: b.get("value") or 0, reverse=True)
    best_posts = best_posts[:posts_limit]
    return {"wiki": wiki, "best_posts": best_posts, "sources": sources}


def _grounding_text(grounding: dict | None) -> str:
    if not grounding:
        return ""
    blocks = []
    wiki = grounding.get("wiki") or []
    if wiki:
        blocks.append(
            "KNOWLEDGE (ground your facts in these, do not invent):\n"
            + "\n".join(f"• {w['title']}: {w['body']}" for w in wiki)
        )
    best = grounding.get("best_posts") or []
    if best:
        blocks.append(
            "OUR BEST-PERFORMING POSTS (match this style/energy, do not copy):\n"
            + "\n".join(
                f"• [{b['platform']}"
                + (f", {b['metric']} {b['value']}" if b.get("metric") else "")
                + f"] {b['caption']}"
                for b in best
            )
        )
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# HERALD fallback (agent-service) — used only when DeepSeek is unavailable
# ---------------------------------------------------------------------------


def _herald_caption(sector: str, brief: str, platform: str) -> str:
    """One HERALD draft via the agent-service; "" when unusable."""
    try:
        from apps.common.agent_client import agent_get, agent_post

        result = agent_post(
            "/agents/herald/draft",
            {"sector": sector, "brief": brief, "count": 1,
             "voice_user": "joseph", "channel": platform},
        )
        proposals = (result or {}).get("proposals") or []
        if not proposals or not isinstance(proposals[0], dict) or not proposals[0].get("id"):
            return ""
        item = agent_get(f"/content/items/{proposals[0]['id']}")
        return str((item or {}).get("body") or "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public: per-channel caption
# ---------------------------------------------------------------------------


def draft_caption(
    *,
    workspace,
    title: str,
    master_text: str,
    platform: str,
    platform_label: str,
    char_limit: int,
    brief: dict | None = None,
    voice: str = "joseph",
    grounding: dict | None = None,
) -> tuple[str, str]:
    """Draft ONE social caption for one channel. Returns (caption, source)
    where source ∈ {"deepseek", "herald", "fallback"}.

    The caption always contains LINK_TOKEN, fits char_limit, and is de-slopped.
    NEVER raises.
    """
    brief = brief or {}
    guardrails = [g for g in (brief.get("guardrails") or []) if isinstance(g, str) and g.strip()]
    assets = [a for a in (brief.get("assets") or []) if isinstance(a, dict) and a.get("url")]

    # 1. DeepSeek (direct) — the primary path.
    if deepseek_client.deepseek_available():
        system = _voice_system(fetch_voice(voice), channel_label=platform_label)
        user_parts = [
            f"Write ONE {platform_label} post (hard maximum {char_limit} characters) "
            f"promoting the article below.",
            f"It MUST contain the literal placeholder token {LINK_TOKEN} exactly once, "
            "where the link to the full article belongs. Do not write a real URL.",
            f"TITLE: {title}",
            f"ARTICLE:\n{master_text[:4000]}",
        ]
        if guardrails:
            user_parts.append("GUARDRAILS (obey strictly):\n" + "\n".join(f"- {g}" for g in guardrails))
        if assets:
            user_parts.append(
                "SUPPORTING ASSETS: "
                + "; ".join(f"{a.get('label') or a['url']} ({a['url']})" for a in assets)
            )
        gt = _grounding_text(grounding)
        if gt:
            user_parts.append(gt)
        out = deepseek_client.chat(system, "\n\n".join(user_parts), max_tokens=700)
        if out:
            return fit_with_token(deslop(out), char_limit), "deepseek"

    # 2. HERALD (agent-service) — fallback when DeepSeek is off.
    try:
        from apps.content_intake.sector_map import map_pillar_to_sector

        sector = map_pillar_to_sector(f"{title} {master_text[:500]}")
    except Exception:
        sector = "general"
    brief_text = (
        f"Write ONE {platform_label} post (max {char_limit} chars) promoting: {title}. "
        f"Include the token {LINK_TOKEN} where the article link belongs.\n{master_text[:2000]}"
    )
    if guardrails:
        brief_text += "\nGuardrails: " + "; ".join(guardrails)
    herald = _herald_caption(sector, brief_text, platform)
    if herald:
        return fit_with_token(deslop(herald), char_limit), "herald"

    # 3. Deterministic fallback — always produces a valid caption.
    return _fallback_caption(title, master_text, char_limit), "fallback"


# ---------------------------------------------------------------------------
# Public: full chat generation (master piece + reply)
# ---------------------------------------------------------------------------


def _extract_title(raw: str) -> tuple[str, str]:
    """Pull a leading 'TITLE: ...' line off the model output; return (title, body)."""
    m = re.match(r"\s*TITLE:\s*(.+?)\s*\n(.*)$", raw, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()[:255], m.group(2).strip()
    return "", raw.strip()


def _ensure_html(body: str) -> str:
    """If the model returned plain text / markdown, wrap paragraphs in <p>."""
    if re.search(r"<(p|h[1-6]|ul|ol|li|strong|em|blockquote)\b", body, re.IGNORECASE):
        return body
    import html as _html

    paras = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
    return "".join(f"<p>{_html.escape(p)}</p>" for p in paras) or "<p></p>"


def generate_content(
    *,
    workspace,
    user_prompt: str,
    voice: str = "joseph",
    channels: list | None = None,
    history: list | None = None,
) -> dict:
    """Generate a grounded, voiced, de-slopped master piece from a chat prompt.

    Returns {"reply", "title", "master_html", "sources", "source"}.
    ``channels`` (list of {"platform_label", ...}) is used only for the reply
    copy. ``history`` is a list of {"role", "content"} prior turns for context.
    NEVER raises.
    """
    channels = channels or []
    grounding = build_grounding(workspace, user_prompt)
    sources = grounding.get("sources") or []
    channel_names = [c.get("platform_label") for c in channels if c.get("platform_label")]

    if not deepseek_client.deepseek_available():
        # No LLM configured: return a helpful, honest stub so the UI still works.
        title = user_prompt.strip()[:80] or "Untitled draft"
        body = _ensure_html(user_prompt.strip())
        reply = (
            "DeepSeek isn't configured yet, so I've saved your prompt as a starting "
            "draft. Once the DEEPSEEK_API_KEY is set I'll write the full piece."
        )
        return {"reply": reply, "title": title, "master_html": deslop_html(body),
                "sources": sources, "source": "fallback"}

    system = _voice_system(fetch_voice(voice))
    parts = [
        "Write a publish-ready long-form piece (a Nexus Brief article) for the "
        "request below. Ground every claim in the KNOWLEDGE provided; do not "
        "invent facts, institutions, or numbers.",
        "Return your answer as:\nTITLE: <a sharp, specific headline>\n<the article "
        "body as clean HTML using only <p>, <h2>, <ul>/<li>, <strong>, <em>>. "
        "No markdown, no code fences, no preamble.",
        f"REQUEST: {user_prompt.strip()}",
    ]
    if history:
        prior = "\n".join(
            f"{h.get('role', 'user').upper()}: {h.get('content', '')[:500]}"
            for h in history[-6:] if h.get("content")
        )
        if prior:
            parts.append("CONVERSATION SO FAR (continue coherently):\n" + prior)
    gt = _grounding_text(grounding)
    if gt:
        parts.append(gt)

    raw = deepseek_client.chat(system, "\n\n".join(parts), max_tokens=1600)
    if not raw:
        # Filtered or failed — degrade to a prompt-derived stub, never 500.
        title = user_prompt.strip()[:80] or "Untitled draft"
        return {
            "reply": "I couldn't complete that draft (the model returned nothing — "
                     "it may have been content-filtered). Try rephrasing.",
            "title": title, "master_html": deslop_html(_ensure_html(user_prompt.strip())),
            "sources": sources, "source": "fallback",
        }

    title, body = _extract_title(raw)
    master_html = deslop_html(_ensure_html(body))
    if not title:
        title = deslop(_plain_text(master_html)).split(". ", 1)[0][:120] or "Untitled draft"

    where = ""
    if channel_names:
        where = " You can push it to " + ", ".join(channel_names[:6]) + "."
    src_note = f" Grounded in {len(sources)} source(s)." if sources else ""
    reply = (
        f"Here's a draft: “{title}”.{src_note} Review it below — tell me what to "
        f"change, or hit Use this to open it in the composer and publish across "
        f"your channels.{where}"
    )
    return {"reply": reply, "title": title, "master_html": master_html,
            "sources": sources, "source": "deepseek"}
