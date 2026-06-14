"""Thin, typed wrappers over agent-service reads for Joseph's surface.

Every wrapper degrades gracefully when the intelligence plane is down or
unconfigured (``AgentClientError``) — it returns a safe default (``[]``/``{}``/
``False``) so a view never 500s on an agent outage. Paths are the FIXED
member-gated agent-service routes (see the spec Grounding); ``AGENT_SERVICE_TOKEN``
already authorizes them. No agent-service changes are introduced here.
"""
from urllib.parse import urlencode

from apps.common.agent_client import AgentClientError, agent_get, agent_post


def _qs(**filters) -> str:
    """Build a stable query string from non-empty filters (sorted for testability)."""
    pairs = [(k, v) for k, v in sorted(filters.items()) if v not in (None, "")]
    return ("?" + urlencode(pairs)) if pairs else ""


# --- threads / dossiers ---------------------------------------------------


def list_threads(**filters) -> list:
    """GET /threads?traffic_light&owner&quintile&stage → items[]."""
    try:
        data = agent_get("/threads" + _qs(**filters)) or {}
    except AgentClientError:
        return []
    return data.get("items", []) if isinstance(data, dict) else (data or [])


def get_thread(thread_id: str) -> dict:
    """GET /threads/{id} → thread detail (+ score, dossier_id, state)."""
    try:
        return agent_get(f"/threads/{thread_id}") or {}
    except AgentClientError:
        return {}


def get_dossier(dossier_id: str) -> dict:
    """GET /dossiers/{id} → dossier (body_md, sources, red_flags, hooks, meta)."""
    try:
        return agent_get(f"/dossiers/{dossier_id}") or {}
    except AgentClientError:
        return {}


def compile_dossier(thread_id: str) -> dict:
    """POST /threads/{id}/dossier (lead) → triggers compile, {dossier_id, sources}."""
    try:
        return agent_post(f"/threads/{thread_id}/dossier") or {}
    except AgentClientError:
        return {}


# --- notifications --------------------------------------------------------


def list_notifications(unread: bool = True) -> list:
    """GET /notifications?unread → items[]."""
    try:
        data = agent_get("/notifications" + _qs(unread=str(unread).lower() if unread else "")) or {}
    except AgentClientError:
        return []
    return data.get("items", []) if isinstance(data, dict) else (data or [])


def mark_read(notification_id: str) -> bool:
    """POST /notifications/{id}/read → True on success, False if agent down."""
    try:
        agent_post(f"/notifications/{notification_id}/read")
        return True
    except AgentClientError:
        return False


# --- knowledge wiki -------------------------------------------------------


def search_pages(q: str = "", entity_type: str = "", limit: int = 0) -> list:
    """GET /knowledge/pages?q&entity_type&limit → pages[]."""
    try:
        data = agent_get("/knowledge/pages" + _qs(q=q, entity_type=entity_type, limit=limit or "")) or {}
    except AgentClientError:
        return []
    return data.get("pages", []) if isinstance(data, dict) else (data or [])


def get_page(slug: str, tier: str = "l1") -> dict:
    """GET /knowledge/pages/{slug}?tier=l0|l1|l2 → page (content, links, aliases)."""
    try:
        return agent_get(f"/knowledge/pages/{slug}" + _qs(tier=tier)) or {}
    except AgentClientError:
        return {}


def page_revisions(slug: str) -> list:
    """GET /knowledge/pages/{slug}/revisions → revisions[]."""
    try:
        data = agent_get(f"/knowledge/pages/{slug}/revisions") or {}
    except AgentClientError:
        return []
    return data.get("revisions", []) if isinstance(data, dict) else (data or [])


# --- content / news -------------------------------------------------------


def list_content(**filters) -> list:
    """GET /content/items?sector&status → items[]."""
    try:
        data = agent_get("/content/items" + _qs(**filters)) or {}
    except AgentClientError:
        return []
    return data.get("items", []) if isinstance(data, dict) else (data or [])


def news_about(org: str, **filters) -> list:
    """GET /news/digest filtered client-side to headlines mentioning ``org``.

    The digest route is sector/africa-filterable but not org-filterable, so we
    narrow it here (the spec calls for org-filtered news in the Intelligence tab).
    """
    if not org:
        return []
    try:
        data = agent_get("/news/digest" + _qs(**filters)) or {}
    except AgentClientError:
        return []
    items = data.get("items", []) if isinstance(data, dict) else (data or [])
    needle = org.lower()
    return [
        i for i in items
        if needle in (str(i.get("title", "")) + " " + str(i.get("summary", ""))).lower()
    ]
