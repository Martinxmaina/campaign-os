"""Gmail API client seam for Joseph's inbound mail feed (Task 11).

Two pure functions, both patchable in tests:

- ``build_gmail_service(integration)`` mints a Gmail v1 service from a stored
  ``GoogleIntegration`` (OAuth2 refresh token → short-lived access token,
  refreshed transparently by ``google.oauth2.credentials.Credentials``).
- ``recent_messages(service, since)`` lists recent inbox messages and fetches
  each into a normalized dict (id, thread_id, subject, from, snippet,
  internal_date) ready for the agent-service ``/ingest`` payload.

No persistence here — the Celery task POSTs to ingest. Mirrors the OAuth2
credential pattern already used by ``integrations/google_calendar.py`` /
``apps/content_intake/sheets_sync.py``.
"""
from __future__ import annotations

from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

# How many recent inbox messages to consider per sync pass.
_MAX_MESSAGES = 25


def build_gmail_service(integration):
    """Build a Gmail v1 service from a ``GoogleIntegration`` row.

    Reuses the Sheets OAuth client id/secret (one Google Cloud OAuth client for
    the workspace); the per-user refresh token comes from the integration.
    """
    creds = Credentials(
        token=None,
        refresh_token=integration.refresh_token,
        token_uri=_TOKEN_URI,
        client_id=settings.GOOGLE_SHEETS_CLIENT_ID,
        client_secret=settings.GOOGLE_SHEETS_CLIENT_SECRET,
        scopes=integration.scopes or [GMAIL_SCOPE],
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list, name: str) -> str:
    """Case-insensitive lookup of a MIME header value."""
    target = name.lower()
    for h in headers or []:
        if str(h.get("name", "")).lower() == target:
            return h.get("value", "") or ""
    return ""


def recent_messages(service, since=None) -> list[dict]:
    """Return recent inbox messages as normalized dicts.

    ``since`` (an epoch-ms string / ``last_synced_at`` cursor) narrows the Gmail
    ``q`` filter to messages newer than the last sync; ``None`` pulls the most
    recent inbox window. Each message is fetched (metadata format) and flattened
    to ``{id, thread_id, subject, from, snippet, internal_date}``.
    """
    query = "in:inbox"
    if since:
        query += f" after:{since}"

    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=_MAX_MESSAGES)
        .execute()
    ) or {}
    ids = [m.get("id") for m in listing.get("messages", []) or [] if m.get("id")]

    out: list[dict] = []
    for mid in ids:
        raw = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=mid,
                format="metadata",
            )
            .execute()
        ) or {}
        headers = (raw.get("payload", {}) or {}).get("headers", [])
        out.append(
            {
                "id": raw.get("id", mid),
                "thread_id": raw.get("threadId", ""),
                "subject": _header(headers, "Subject"),
                "from": _header(headers, "From"),
                "snippet": raw.get("snippet", "") or "",
                "internal_date": raw.get("internalDate", ""),
            }
        )
    return out
