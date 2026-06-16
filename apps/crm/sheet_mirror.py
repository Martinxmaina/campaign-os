"""Daily mirror of the live CRM pipeline into a Google Sheet tab (read-WRITE).

Writes one row per OutreachThread into a DEDICATED tab (created if missing) so it
never clobbers the user's own tabs. No-ops cleanly when the sheet isn't configured
or the Google token lacks the read-write `spreadsheets` scope (requires a re-consent
with that scope — the read-only intake token cannot write).
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_RW_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_HEADER = [
    "Org", "Stage", "Owner", "Track", "Traffic light",
    "Quintile", "Next action", "Due", "Last touch", "Updated",
]


def _rw_service():
    """A read-WRITE Sheets v4 service from the GOOGLE_SHEETS_* OAuth creds, or None
    if creds are absent. google libs imported lazily (Celery autodiscover safe)."""
    cid = getattr(settings, "GOOGLE_SHEETS_CLIENT_ID", "")
    cs = getattr(settings, "GOOGLE_SHEETS_CLIENT_SECRET", "")
    rt = getattr(settings, "GOOGLE_SHEETS_REFRESH_TOKEN", "")
    if not (cid and cs and rt):
        return None
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None, refresh_token=rt, token_uri=_TOKEN_URI,
        client_id=cid, client_secret=cs, scopes=[_RW_SCOPE],
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _pipeline_rows():
    from django.utils import timezone

    from apps.crm.models import OutreachThread

    stamp = timezone.now().strftime("%Y-%m-%d %H:%M UTC")
    rows = [_HEADER]
    qs = OutreachThread.objects.select_related("org", "owner").order_by("stage", "-quintile")
    for t in qs:
        rows.append([
            t.org.name if t.org else "",
            t.stage,
            (t.owner.email if t.owner else ""),
            t.track or "",
            t.traffic_light,
            t.quintile or "",
            t.next_action or "",
            t.next_action_due.isoformat() if t.next_action_due else "",
            t.last_touch.date().isoformat() if t.last_touch else "",
            stamp,
        ])
    return rows


def ensure_tab(service, sheet_id: str, tab: str) -> None:
    """Create ``tab`` if it doesn't exist — never touches existing tabs."""
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if tab not in titles:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
        ).execute()


def mirror_pipeline_to_sheet(service=None) -> dict:
    """Overwrite the configured dedicated tab with the current CRM pipeline."""
    sheet_id = getattr(settings, "CRM_TRACKER_SHEET_ID", "") or ""
    tab = getattr(settings, "CRM_TRACKER_TAB", "") or "Campaign OS — Pipeline"
    if not sheet_id:
        return {"skipped": "no-sheet-configured"}
    svc = service or _rw_service()
    if svc is None:
        return {"skipped": "no-credentials"}

    rows = _pipeline_rows()
    ensure_tab(svc, sheet_id, tab)
    rng = f"'{tab}'"
    svc.spreadsheets().values().clear(spreadsheetId=sheet_id, range=rng).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=sheet_id, range=f"{rng}!A1",
        valueInputOption="RAW", body={"values": rows},
    ).execute()
    return {"rows": len(rows) - 1, "tab": tab}
