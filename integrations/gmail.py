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

import base64

from django.conf import settings

_TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

# How many recent inbox messages to consider per sync pass.
_MAX_MESSAGES = 25


def build_gmail_service(integration):
    """Build a Gmail v1 service from a ``GoogleIntegration`` row.

    Reuses the Sheets OAuth client id/secret (one Google Cloud OAuth client for
    the workspace); the per-user refresh token comes from the integration.

    The google client libs are imported lazily here (mirroring
    ``apps/content_intake/sheets_sync.py``) so importing this module — and the
    Celery task that does, during autodiscover — never requires ``google``. The
    sync no-ops without a ``GoogleIntegration`` row, so this is only reached once
    a mailbox is actually connected.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

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


def send_message(
    service,
    *,
    to: str,
    subject: str,
    body_html: str,
    sender: str | None = None,
    headers: dict | None = None,
) -> str:
    """Send an HTML email through the Gmail API; return the sent message id.

    Builds a MIME message with stdlib ``email.mime`` (no google libs needed here —
    only the already-built ``service`` and the standard library), base64url-encodes
    the serialized bytes, and calls
    ``service.users().messages().send(userId="me", body={"raw": ...})``.

    ``sender`` sets the ``From`` header (the mailbox identity); Gmail sends as the
    authenticated user regardless, but a friendly ``From`` is set when supplied.
    ``headers`` carries optional extra MIME headers — notably ``In-Reply-To`` and
    ``References`` for threading replies — and is applied verbatim when present.
    The transport is deliberately dumb: deliverability (suppression, cap/ramp,
    unsubscribe header + footer) is enforced upstream in the adapter, never here.
    """
    from email.mime.text import MIMEText

    message = MIMEText(body_html, "html")
    message["To"] = to
    message["Subject"] = subject
    if sender:
        message["From"] = sender
    for name, value in (headers or {}).items():
        if value:
            message[name] = value

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    ) or {}
    return sent.get("id", "")
