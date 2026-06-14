"""Celery tasks backing Joseph's external feeds.

Task 10 — ``sync_google_calendar``: for every stored ``GoogleIntegration``,
build a Calendar client, pull the next two weeks of events, fuzzy-match each
against the org names of agent-service threads, and upsert a ``CalendarEvent``.
A confident match (ratio > 0.9) auto-links the event to its thread and fires a
notification; an ambiguous one (0.6–0.9) is left unlinked so it surfaces as a
linkage suggestion in the action queue.

Safe to deploy before Joseph's OAuth re-consent: with no ``GoogleIntegration``
row the task no-ops (``{"skipped": "no-credentials"}``) and never raises.

``build_calendar_service``/``upcoming_events`` are re-exported from
``integrations.google_calendar`` so tests patch them on this module.
"""
from __future__ import annotations

import logging
from difflib import SequenceMatcher

from celery import shared_task
from django.utils import timezone

from apps.joseph import readers
from integrations.google_calendar import build_calendar_service, upcoming_events

logger = logging.getLogger(__name__)

# Auto-link at/above this fuzzy ratio; 0.6–0.9 is a suggestion (left unlinked).
AUTO_LINK_THRESHOLD = 0.9
SUGGEST_THRESHOLD = 0.6

__all__ = [
    "sync_google_calendar",
    "best_thread_match",
    "build_calendar_service",
    "upcoming_events",
]


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _attendee_tokens(attendees: list) -> str:
    """Flatten attendee emails into a whitespace string of name+domain tokens
    (``officer@rockefellerfoundation.org`` → ``officer rockefellerfoundation``).
    """
    parts: list[str] = []
    for a in attendees or []:
        email = str((a or {}).get("email", ""))
        if "@" not in email:
            continue
        local, _, domain = email.partition("@")
        domain_main = domain.split(".")[0] if domain else ""
        parts.append(local.replace(".", " "))
        parts.append(domain_main)
    return _norm(" ".join(parts))


def best_thread_match(title: str, attendees: list, threads: list) -> tuple[str, float]:
    """Return ``(thread_id, score)`` of the thread whose org best matches the
    event title/attendees. ``("", 0.0)`` when there are no threads.

    Score = max similarity of the org name against (a) the event title and
    (b) the attendee-domain tokens, using difflib token-set ratios. A direct
    substring hit (org name appears in the title/attendees) scores 1.0.
    """
    haystack_title = _norm(title)
    haystack_att = _attendee_tokens(attendees)
    best_id, best_score = "", 0.0
    for t in threads or []:
        org = _norm(t.get("org", ""))
        if not org:
            continue
        score = max(
            _similarity(org, haystack_title),
            _similarity(org, haystack_att),
        )
        if score > best_score:
            best_id, best_score = str(t.get("id", "")), score
    return best_id, best_score


def _similarity(org: str, haystack: str) -> float:
    """Similarity of an org name against a haystack string.

    A clean substring match (the full org name, or the longest org token of
    length ≥ 5, appears in the haystack) is treated as a confident 1.0. Else we
    fall back to a difflib ratio over the org and the best-aligned window.
    """
    if not org or not haystack:
        return 0.0
    if org in haystack:
        return 1.0
    # longest distinctive token (drops generic words like "foundation")
    tokens = [tok for tok in org.split() if len(tok) >= 5]
    for tok in sorted(tokens, key=len, reverse=True):
        if tok in haystack:
            return 1.0
    return SequenceMatcher(None, org, haystack).ratio()


def _resolve_workspace(integration):
    """Resolve the workspace a member's calendar events belong to.

    Prefers the workspace where the member holds a principal-grade role
    (owner/admin/principal) — Joseph's operating house — over the auto-created
    personal sandbox every user gets on signup; ties break on most-recently
    joined for determinism. ``None`` when the user has no (active) workspace, in
    which case the task skips that integration.
    """
    from apps.members.models import WorkspaceMembership

    qs = (
        WorkspaceMembership.objects.filter(
            user=integration.user, workspace__is_archived=False
        )
        .select_related("workspace")
        .order_by("-added_at")
    )
    memberships = list(qs)
    if not memberships:
        return None
    principal_roles = {
        WorkspaceMembership.WorkspaceRole.PRINCIPAL,
        WorkspaceMembership.WorkspaceRole.ADMIN,
        WorkspaceMembership.WorkspaceRole.OWNER,
    }
    for m in memberships:
        if m.workspace_role in principal_roles:
            return m.workspace
    return memberships[0].workspace


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def sync_google_calendar(self):
    """Pull upcoming Google Calendar events for every integration and upsert
    them as fuzzy-linked ``CalendarEvent`` rows.

    Returns a summary dict; no-ops to ``{"skipped": "no-credentials"}`` when
    there are no integrations (safe to run before OAuth re-consent).
    """
    from apps.joseph.models import CalendarEvent, GoogleIntegration

    integrations = list(GoogleIntegration.objects.select_related("user").all())
    if not integrations:
        return {"skipped": "no-credentials"}

    threads = readers.list_threads()
    upserted = 0
    linked = 0

    for integration in integrations:
        workspace = _resolve_workspace(integration)
        if workspace is None:
            continue
        try:
            service = build_calendar_service(integration)
            events = upcoming_events(service)
        except Exception as exc:  # network / auth / API — keep other users going
            logger.warning(
                "sync_google_calendar: fetch failed for user %s: %s",
                integration.user_id,
                exc,
            )
            continue

        for ev in events:
            gid = ev.get("id")
            if not gid:
                continue
            title = ev.get("summary", "") or ""
            attendees = ev.get("attendees", []) or []
            start = _parse_dt(ev.get("start", {}))
            end = _parse_dt(ev.get("end", {}))

            thread_id, score = best_thread_match(title, attendees, threads)
            link = thread_id if score >= AUTO_LINK_THRESHOLD else ""

            obj, created = CalendarEvent.objects.update_or_create(
                google_event_id=gid,
                defaults={
                    "workspace": workspace,
                    "title": title[:500],
                    "start": start or timezone.now(),
                    "end": end,
                    "attendees": attendees,
                    "linked_thread_id": link,
                    "raw": ev,
                },
            )
            upserted += 1
            if link:
                linked += 1
                if created:
                    _notify_auto_link(obj, score)

        integration.last_synced_at = timezone.now()
        integration.save(update_fields=["last_synced_at", "updated_at"])

    return {"upserted": upserted, "linked": linked}


def _notify_auto_link(event, score: float) -> None:
    """Fire an agent-service notification for a confident auto-link (best-effort)."""
    readers.create_notification(
        "calendar_auto_link",
        f"Linked meeting “{event.title}” to a thread "
        f"(match {int(score * 100)}%).",
        thread_id=event.linked_thread_id,
        action={"href": f"/joseph/thread/{event.linked_thread_id}/"},
    )


def _parse_dt(node: dict):
    """Parse a Calendar API start/end node (``dateTime`` or all-day ``date``)."""
    from django.utils.dateparse import parse_datetime

    if not isinstance(node, dict):
        return None
    raw = node.get("dateTime") or node.get("date")
    if not raw:
        return None
    dt = parse_datetime(raw)
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt
