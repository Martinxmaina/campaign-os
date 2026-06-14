"""Google Calendar API client seam for Joseph's calendar feed (Task 10).

Two pure functions, both patchable in tests:

- ``build_calendar_service(integration)`` mints a Calendar v3 service from a
  stored ``GoogleIntegration`` (OAuth2 refresh token → short-lived access token,
  refreshed transparently by ``google.oauth2.credentials.Credentials``).
- ``upcoming_events(service, days)`` returns the next ``days`` of single,
  time-ordered events as raw Calendar API resource dicts.

No persistence here — the Celery task upserts. Mirrors the OAuth2 credential
pattern already used by ``apps/content_intake/sheets_sync.py``.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

_TOKEN_URI = "https://oauth2.googleapis.com/token"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def build_calendar_service(integration):
    """Build a Calendar v3 service from a ``GoogleIntegration`` row.

    Reuses the Sheets OAuth client id/secret (one Google Cloud OAuth client for
    the workspace); the per-user refresh token comes from the integration.

    The google client libs are imported lazily here (mirroring
    ``apps/content_intake/sheets_sync.py``) so merely importing this module — and
    the Celery task that does, during autodiscover — never requires ``google``.
    The sync tasks no-op without a ``GoogleIntegration`` row, so this is only
    reached once a mailbox/calendar is actually connected.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=integration.refresh_token,
        token_uri=_TOKEN_URI,
        client_id=settings.GOOGLE_SHEETS_CLIENT_ID,
        client_secret=settings.GOOGLE_SHEETS_CLIENT_SECRET,
        scopes=integration.scopes or [CALENDAR_SCOPE],
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def upcoming_events(service, days: int = 14) -> list[dict]:
    """Return the next ``days`` of upcoming events (raw API resources)."""
    now = timezone.now()
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days)).isoformat()
    resp = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute()
    )
    return resp.get("items", []) or []
