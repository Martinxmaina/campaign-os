"""Google Sheets → ContentIntake synchronisation.

Public entry-point:
    sync_sheet_to_intake(workspace, sheet_id="", sheet_range="") -> dict

Returns a summary dict:
    {"created": N, "updated": N, "skipped": N, "review_queue": N, "errors": N}

Design notes
------------
- Row dedup uses a SHA-256 hash of the raw row JSON so re-syncing the same
  unchanged row is a no-op (no DB write).
- Rows whose ``external_id`` is a template sentinel ("EXAMPLE", "example",
  "template") are skipped silently.
- Rows whose pillar_theme is "EXAMPLE" are also silently skipped.
- Normalisation failures (bad sensitivity / status) are quarantined in
  IntakeReviewItem with the original row preserved; the ContentIntake row is
  still created, but with sensitivity=private_hold so it cannot be scheduled.
- ``_get_sheet_rows`` is a seam kept separate so tests can patch it without
  touching the network.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from apps.workspaces.models import Workspace

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel / skip-list
# ---------------------------------------------------------------------------

_SKIP_EXTERNAL_IDS: frozenset[str] = frozenset({"EXAMPLE", "example", "template"})
_SKIP_PILLAR_THEMES: frozenset[str] = frozenset({"EXAMPLE"})

# Column indices (0-based) expected in Sheet1!A:P
# Canonical column order matches the planning register template spec:
#   A   B           C             D              E      F            G
#   ID  Date added  Submitted by  Pillar/Theme   Angle  Proof point  Target audience
#   H                I        J         K        L       M                  N    O        P
#   Sensitivity flag Channel  Campaign  Priority  Status  Owner  Target publish date  Notes  Doc links
_COL_EXTERNAL_ID = 0
# Column 1 (B) is "Date added" from the sheet; ContentIntake has no
# date_added model field — the value is preserved in the row_hash so
# a later date correction re-syncs the row, but it is not stored
# separately.  Do not add a bare _COL_DATE_ADDED constant here unless
# it is actually read in the sync loop.
_COL_SUBMITTED_BY_RAW = 2
_COL_PILLAR = 3
_COL_ANGLE = 4
_COL_PROOF_POINT = 5
_COL_TARGET_AUDIENCE = 6
_COL_SENSITIVITY = 7
_COL_CHANNELS = 8
_COL_CAMPAIGN = 9
_COL_PRIORITY = 10
_COL_STATUS = 11
_COL_OWNER_RAW = 12
_COL_TARGET_DATE = 13
_COL_NOTES = 14
_COL_REF_LINKS = 15


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _build_credentials():
    """Return Google credentials using OAuth2 refresh token (preferred)
    or service-account JSON (fallback). Returns None when neither is configured."""
    # --- OAuth2 path (preferred; works when org policy blocks SA keys) -------
    client_id = settings.GOOGLE_SHEETS_CLIENT_ID
    client_secret = settings.GOOGLE_SHEETS_CLIENT_SECRET
    refresh_token = settings.GOOGLE_SHEETS_REFRESH_TOKEN

    if client_id and client_secret and refresh_token:
        from google.oauth2.credentials import Credentials
        return Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=_TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=[_SHEETS_SCOPE],
        )

    # --- Service-account JSON fallback ---------------------------------------
    sa_json = settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON
    if sa_json:
        import json as _json
        from google.oauth2 import service_account
        info = _json.loads(sa_json)
        return service_account.Credentials.from_service_account_info(
            info, scopes=[_SHEETS_SCOPE]
        )

    return None


def _get_sheet_rows(sheet_id: str, sheet_range: str) -> list[list[str]]:
    """Fetch raw rows from a Google Sheet.

    Returns an empty list when no credentials are configured
    (tests and local dev without credentials get a no-op sync).

    The first row returned by the Sheets API is the header; callers must
    skip row 0.
    """
    creds = _build_credentials()
    if creds is None:
        logger.debug("No Google Sheets credentials configured — skipping fetch")
        return []

    try:
        from googleapiclient.discovery import build
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=sheet_range)
            .execute()
        )
        return result.get("values", [])
    except Exception:
        logger.exception("Failed to fetch Google Sheet id=%s range=%s", sheet_id, sheet_range)
        return []


def _row_value(row: list[str], idx: int, default: str = "") -> str:
    """Safe column access — returns default when row is shorter than idx."""
    try:
        return str(row[idx]).strip()
    except IndexError:
        return default


def _compute_hash(row: list[str]) -> str:
    """SHA-256 of the JSON-serialised row (stable, order-sensitive)."""
    return hashlib.sha256(json.dumps(row, ensure_ascii=False).encode()).hexdigest()


def _parse_target_date(raw: str):
    """Parse a target-date cell; return a date or None."""
    if not raw:
        return None
    try:
        from dateutil import parser as dateparser
        return dateparser.parse(raw, dayfirst=False).date()
    except Exception:
        return None


def _map_priority(raw: str) -> str:
    """Map raw priority to single-char canonical: H/M/L."""
    r = raw.strip().upper()
    if r in {"H", "HIGH"}:
        return "H"
    if r in {"L", "LOW"}:
        return "L"
    return "M"  # default medium


# ---------------------------------------------------------------------------
# Public sync function
# ---------------------------------------------------------------------------

def sync_sheet_to_intake(
    workspace: "Workspace",
    sheet_id: str = "",
    sheet_range: str = "",
) -> dict:
    """Sync Google Sheet rows into ContentIntake records for *workspace*.

    Parameters
    ----------
    workspace:
        The workspace whose intake records will be created/updated.
    sheet_id:
        Google Sheet ID.  Falls back to ``settings.CONTENT_INTAKE_SHEET_ID``.
    sheet_range:
        A1 notation range.  Falls back to ``settings.CONTENT_INTAKE_SHEET_RANGE``.

    Returns a stats dict with keys: created, updated, skipped, review_queue, errors.
    """
    from apps.content_intake.models import ContentIntake, IntakeReviewItem, UnblockCondition
    from apps.content_intake.normalization import (
        extract_unblock_conditions,
        map_status,
        normalize_sensitivity,
        parse_channels,
    )

    effective_sheet_id = sheet_id or settings.CONTENT_INTAKE_SHEET_ID
    effective_range = sheet_range or settings.CONTENT_INTAKE_SHEET_RANGE

    rows = _get_sheet_rows(effective_sheet_id, effective_range)

    stats = {"created": 0, "updated": 0, "skipped": 0, "review_queue": 0, "errors": 0}

    # Row 0 is the header — skip it
    data_rows = rows[1:] if rows else []

    for row in data_rows:
        external_id = _row_value(row, _COL_EXTERNAL_ID)
        pillar_theme = _row_value(row, _COL_PILLAR)

        # --- Skip sentinel / template rows ---------------------------------
        if external_id in _SKIP_EXTERNAL_IDS or pillar_theme in _SKIP_PILLAR_THEMES:
            stats["skipped"] += 1
            continue

        if not external_id:
            # Rows with no ID are skipped (likely blank trailing rows)
            stats["skipped"] += 1
            continue

        # --- Row hash dedup ------------------------------------------------
        row_hash = _compute_hash(row)
        existing_qs = ContentIntake.objects.filter(
            workspace=workspace, external_id=external_id
        )
        if existing_qs.filter(row_hash=row_hash).exists():
            stats["skipped"] += 1
            continue

        # --- Normalise columns ---------------------------------------------
        raw_sensitivity = _row_value(row, _COL_SENSITIVITY)
        sensitivity, sens_needs_review = normalize_sensitivity(raw_sensitivity)

        raw_status = _row_value(row, _COL_STATUS)
        status, status_needs_review = map_status(raw_status)

        channels = parse_channels(_row_value(row, _COL_CHANNELS))
        notes_raw = _row_value(row, _COL_NOTES)
        conditions_data = extract_unblock_conditions(notes_raw)

        target_date = _parse_target_date(_row_value(row, _COL_TARGET_DATE))
        priority = _map_priority(_row_value(row, _COL_PRIORITY))

        # --- Build IntakeReviewItem if normalisation failed ----------------
        needs_review = sens_needs_review or status_needs_review
        raw_row_payload = row  # preserve original list

        review_reason = None
        review_detail = ""
        if sens_needs_review:
            review_reason = IntakeReviewItem.ReviewReason.SENSITIVITY_UNRECOGNIZED
            review_detail = f"Unrecognized sensitivity value: {raw_sensitivity!r}"
        elif status_needs_review:
            review_reason = IntakeReviewItem.ReviewReason.STATUS_UNMAPPED
            review_detail = f"Unmapped status value: {raw_status!r}"

        if needs_review and review_reason:
            IntakeReviewItem.objects.update_or_create(
                workspace=workspace,
                external_id=external_id,
                defaults={
                    "raw_row": raw_row_payload,
                    "reason": review_reason,
                    "detail": review_detail,
                    "resolved": False,
                },
            )
            stats["review_queue"] += 1
            # Fail-closed: force sensitivity to private_hold so the row
            # cannot be scheduled.
            sensitivity = "private_hold"

        # --- Upsert ContentIntake -----------------------------------------
        try:
            defaults = {
                "row_hash": row_hash,
                "submitted_by_raw": _row_value(row, _COL_SUBMITTED_BY_RAW),
                "pillar_theme": pillar_theme,
                "angle": _row_value(row, _COL_ANGLE),
                "proof_point": _row_value(row, _COL_PROOF_POINT),
                "target_audience": _row_value(row, _COL_TARGET_AUDIENCE),
                "sensitivity": sensitivity,
                "status": status,
                "channel_targets": channels,
                "priority": priority,
                "campaign": _row_value(row, _COL_CAMPAIGN),
                "owner_raw": _row_value(row, _COL_OWNER_RAW),
                "target_publish_date": target_date,
                "notes_raw": notes_raw,
                "reference_links": [
                    lnk.strip()
                    for lnk in _row_value(row, _COL_REF_LINKS).split(",")
                    if lnk.strip()
                ],
                "last_synced_at": timezone.now(),
                "sync_error": "",
            }

            obj, created = ContentIntake.objects.update_or_create(
                workspace=workspace,
                external_id=external_id,
                defaults=defaults,
            )

            if created:
                stats["created"] += 1
            else:
                stats["updated"] += 1

            # --- Upsert UnblockConditions ----------------------------------
            for cdata in conditions_data:
                UnblockCondition.objects.get_or_create(
                    intake=obj,
                    condition_type=cdata["type"],
                    defaults={
                        "description": cdata["description"],
                        "status": "open",
                    },
                )

        except Exception:
            logger.exception(
                "Error processing row external_id=%s for workspace=%s",
                external_id,
                workspace.pk,
            )
            stats["errors"] += 1

    return stats
