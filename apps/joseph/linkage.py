"""Calendar ↔ thread auto-linking (TB.3).

A synced ``CalendarEvent`` is matched against the canonical CRM (Organization
name + the primary Contact's email/name) so a confident meeting auto-links to
its deal thread and an ambiguous one stays a *suggestion* the principal confirms
by hand. The two public entry points:

- ``match_event_to_thread(event, *, threshold=0.9) -> (thread|None, confidence)``
  scores every CRM ``OutreachThread`` against the event's title + attendees and
  returns the best ``OutreachThread`` *only* when it clears ``threshold``; the
  confidence is always returned so a mid-band (0.5–0.9) hit can be surfaced as a
  suggestion by ``JosephIntelligence._unlinked_calendar_events``.
- ``link_event(event, thread)`` is the setter (writes ``linked_thread_id`` +
  advances ``briefing_status`` to ``linked``); ``auto_link_event(event)`` ties
  the two together for the sync path — it links only a confident match.

Scoring is a stdlib token-set ratio (rapidfuzz-style, but with no third-party
dependency) over normalized tokens, plus an exact attendee-email vs contact
-email shortcut to 1.0. Unlike the coarse substring matcher in ``tasks`` (which
treats any shared distinctive token as a full hit), the token-set ratio keeps a
partial name overlap (e.g. "Rockefeller Brothers Fund" vs "Rockefeller catch
up") in the mid band so it is offered as a suggestion rather than silently
linked.
"""
from __future__ import annotations

from difflib import SequenceMatcher


def _norm(text: str) -> str:
    """Lowercase + collapse whitespace; the em dash separates, not joins."""
    return " ".join(str(text or "").lower().replace("\u2014", " ").split())


def _tokens(text: str) -> set[str]:
    return set(_norm(text).split())


def _token_set_ratio(a: str, b: str) -> float:
    """rapidfuzz-style token_set_ratio over difflib (0.0–1.0).

    Compares the sorted intersection of the two token sets against each side's
    full sorted token string, so word order and extra context words (e.g. a
    "— climate sync" suffix on the title) don't sink an otherwise full match.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    s_inter = " ".join(sorted(inter))
    s_a = (s_inter + " " + " ".join(sorted(ta - tb))).strip()
    s_b = (s_inter + " " + " ".join(sorted(tb - ta))).strip()
    ratios = [SequenceMatcher(None, s_a, s_b).ratio()]
    if s_inter:
        ratios.append(SequenceMatcher(None, s_inter, s_a).ratio())
        ratios.append(SequenceMatcher(None, s_inter, s_b).ratio())
    return max(ratios)


def _attendee_emails(attendees) -> list[str]:
    out: list[str] = []
    for a in attendees or []:
        email = str((a or {}).get("email", "")).lower().strip()
        if "@" in email:
            out.append(email)
    return out


def _attendee_tokens(attendees) -> str:
    """Flatten attendee emails into name + domain-stem tokens
    (``officer@rockfound.org`` → ``officer rockfound``)."""
    parts: list[str] = []
    for email in _attendee_emails(attendees):
        local, _, domain = email.partition("@")
        parts.append(local.replace(".", " "))
        parts.append(domain.split(".")[0] if domain else "")
    return " ".join(parts)


def _attendee_names(attendees) -> str:
    parts = []
    for a in attendees or []:
        name = str((a or {}).get("displayName") or (a or {}).get("name") or "")
        if name:
            parts.append(name)
    return " ".join(parts)


def _score_thread(event, thread) -> float:
    """Confidence that ``event`` is this CRM ``OutreachThread``'s meeting.

    Signals (the max wins): an exact attendee-email vs primary-contact-email hit
    (1.0); the org name's token-set ratio against the event title + attendee
    tokens; and the contact name's token-set ratio against title + attendee
    names. ``0.0`` when the thread has no org and no contact signal.
    """
    org = thread.org.name if thread.org_id else ""
    contact = thread.primary_contact
    contact_email = (contact.email if contact else "").lower().strip()
    contact_name = contact.full_name if contact else ""

    emails = _attendee_emails(event.attendees)
    if contact_email and contact_email in emails:
        return 1.0

    haystack = _norm(event.title) + " " + _attendee_tokens(event.attendees)
    score = _token_set_ratio(org, haystack) if org else 0.0

    if contact_name:
        name_hay = _norm(event.title) + " " + _norm(_attendee_names(event.attendees))
        score = max(score, _token_set_ratio(contact_name, name_hay))

    return score


def match_event_to_thread(event, *, threshold: float = 0.9):
    """Best CRM thread for ``event`` and its confidence.

    Returns ``(thread, confidence)`` when the best score clears ``threshold``
    (a confident auto-link), else ``(None, confidence)`` — the caller decides
    whether the sub-threshold confidence is a mid-band suggestion (≥0.5) or
    noise (<0.5). Workspace-agnostic: the CRM is org-canonical, not workspace
    -scoped, so we score every thread.
    """
    from apps.crm.models import OutreachThread

    best_thread = None
    best_score = 0.0
    for thread in OutreachThread.objects.select_related("org", "primary_contact"):
        score = _score_thread(event, thread)
        if score > best_score:
            best_thread, best_score = thread, score

    if best_thread is not None and best_score >= threshold:
        return best_thread, best_score
    return None, best_score


def link_event(event, thread):
    """Link ``event`` to ``thread`` and advance the cascade to ``linked``."""
    event.linked_thread_id = str(thread.id)
    event.briefing_status = "linked"
    event.save(update_fields=["linked_thread_id", "briefing_status", "updated_at"])
    return event


def auto_link_event(event, *, threshold: float = 0.9):
    """Auto-link ``event`` iff a confident (≥``threshold``) thread match exists.

    Returns the linked ``OutreachThread`` on success, else ``None`` — a mid-band
    match is deliberately left unlinked so it surfaces as a suggestion in the
    action queue (``JosephIntelligence._unlinked_calendar_events``).
    """
    thread, _confidence = match_event_to_thread(event, threshold=threshold)
    if thread is None:
        return None
    link_event(event, thread)
    return thread
