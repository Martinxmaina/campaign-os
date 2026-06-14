"""Tests for the CRM import wizard's parsing + mapping + dedup + commit core.

Covers ``apps.crm.import_wizard``:

  * ``parse_rows(file_bytes, filename)`` — CSV (stdlib csv) and XLSX
    (openpyxl, imported lazily) → a list of header→value dicts.
  * ``parse_sheet_url(url)`` — reuse the content_intake grid reader (mocked)
    → the same list-of-dicts shape.
  * ``apply_mapping(rows, mapping)`` — source headers → CRM fields
    (org_name, contact_name, contact_email, role, stage, track).
  * ``dedupe(mapped_rows)`` → ``(new, matched)`` where a row whose
    org_name+email already exists in the DB is matched (case-insensitive).
  * ``commit_rows(new_rows)`` — creates Organization/Contact/OutreachThread,
    returns per-row results; a row missing org_name → error, never a crash.
"""
from __future__ import annotations

import csv
import io
from unittest.mock import patch

import pytest

from apps.crm import import_wizard
from apps.crm.models import Contact, Organization, OutreachThread

# Two source rows the team's spreadsheet might contain (raw headers).
CSV_HEADERS = ["Organization", "Name", "Email", "Title", "Stage", "Track"]
ROW_A = ["Rockefeller", "Dr. Okonkwo", "okonkwo@rockefeller.org", "VP Programs", "engaged", "ai10bn"]
ROW_B = ["Gates Foundation", "Jane Doe", "jane@gates.org", "Director", "targeted", "core"]

MAPPING = {
    "Organization": "org_name",
    "Name": "contact_name",
    "Email": "contact_email",
    "Title": "role",
    "Stage": "stage",
    "Track": "track",
}


def _csv_bytes() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADERS)
    w.writerow(ROW_A)
    w.writerow(ROW_B)
    return buf.getvalue().encode("utf-8")


def _xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(CSV_HEADERS)
    ws.append(ROW_A)
    ws.append(ROW_B)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# parse_rows
# ---------------------------------------------------------------------------


def test_parse_rows_csv():
    rows = import_wizard.parse_rows(_csv_bytes(), "contacts.csv")
    assert len(rows) == 2
    assert rows[0]["Organization"] == "Rockefeller"
    assert rows[0]["Email"] == "okonkwo@rockefeller.org"
    assert rows[1]["Name"] == "Jane Doe"
    # Every row is a header->value dict with all headers as keys.
    assert set(rows[0].keys()) == set(CSV_HEADERS)


def test_parse_rows_xlsx():
    rows = import_wizard.parse_rows(_xlsx_bytes(), "contacts.xlsx")
    assert len(rows) == 2
    assert rows[0]["Organization"] == "Rockefeller"
    assert rows[1]["Track"] == "core"
    assert set(rows[0].keys()) == set(CSV_HEADERS)


def test_parse_rows_unsupported_extension():
    with pytest.raises(ValueError):
        import_wizard.parse_rows(b"whatever", "contacts.txt")


# ---------------------------------------------------------------------------
# parse_sheet_url
# ---------------------------------------------------------------------------


def test_parse_sheet_url_reuses_grid_reader():
    url = "https://docs.google.com/spreadsheets/d/ABC123sheetid/edit#gid=0"
    grid = [
        [{"formattedValue": h} for h in CSV_HEADERS],
        [{"formattedValue": v} for v in ROW_A],
        [{"formattedValue": v} for v in ROW_B],
    ]
    with patch(
        "apps.crm.import_wizard._get_sheet_grid", return_value=grid
    ) as mock_grid:
        rows = import_wizard.parse_sheet_url(url)

    # Called with the extracted sheet id.
    assert mock_grid.call_args[0][0] == "ABC123sheetid"
    assert len(rows) == 2
    assert rows[0]["Organization"] == "Rockefeller"
    assert rows[1]["Email"] == "jane@gates.org"


# ---------------------------------------------------------------------------
# apply_mapping
# ---------------------------------------------------------------------------


def test_apply_mapping_maps_headers_to_crm_fields():
    rows = import_wizard.parse_rows(_csv_bytes(), "contacts.csv")
    mapped = import_wizard.apply_mapping(rows, MAPPING)
    assert mapped[0] == {
        "org_name": "Rockefeller",
        "contact_name": "Dr. Okonkwo",
        "contact_email": "okonkwo@rockefeller.org",
        "role": "VP Programs",
        "stage": "engaged",
        "track": "ai10bn",
    }
    # Unmapped CRM fields simply don't appear / are blank.
    assert mapped[1]["org_name"] == "Gates Foundation"


def test_apply_mapping_ignores_unmapped_columns():
    rows = [{"Organization": "Acme", "Junk": "ignore-me"}]
    mapped = import_wizard.apply_mapping(rows, {"Organization": "org_name"})
    assert mapped[0]["org_name"] == "Acme"
    assert "Junk" not in mapped[0].values()


# ---------------------------------------------------------------------------
# dedupe
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dedupe_splits_new_and_matched():
    org = Organization.objects.create(name="Rockefeller", type="funder")
    Contact.objects.create(org=org, full_name="Dr. Okonkwo", email="okonkwo@rockefeller.org")

    rows = import_wizard.apply_mapping(
        import_wizard.parse_rows(_csv_bytes(), "c.csv"), MAPPING
    )
    new, matched = import_wizard.dedupe(rows)

    assert len(matched) == 1
    assert matched[0]["contact_email"] == "okonkwo@rockefeller.org"
    assert len(new) == 1
    assert new[0]["org_name"] == "Gates Foundation"


@pytest.mark.django_db
def test_dedupe_is_case_insensitive():
    org = Organization.objects.create(name="rockefeller")
    Contact.objects.create(org=org, full_name="x", email="OKONKWO@ROCKEFELLER.ORG")

    rows = [{"org_name": "Rockefeller", "contact_email": "okonkwo@rockefeller.org"}]
    new, matched = import_wizard.dedupe(rows)
    assert len(matched) == 1
    assert len(new) == 0


# ---------------------------------------------------------------------------
# commit_rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_commit_rows_creates_org_contact_thread():
    rows = import_wizard.apply_mapping(
        import_wizard.parse_rows(_csv_bytes(), "c.csv"), MAPPING
    )
    results = import_wizard.commit_rows(rows)

    assert len(results) == 2
    assert all(r["status"] == "created" for r in results)

    org = Organization.objects.get(name="Rockefeller")
    contact = Contact.objects.get(email="okonkwo@rockefeller.org")
    assert contact.org_id == org.id
    assert contact.role == "VP Programs"
    thread = OutreachThread.objects.get(org=org)
    assert thread.primary_contact_id == contact.id
    assert thread.stage == "engaged"
    assert thread.track == "ai10bn"


@pytest.mark.django_db
def test_commit_rows_missing_org_name_is_error_not_crash():
    rows = [
        {"org_name": "", "contact_name": "Nobody", "contact_email": "n@x.org"},
        {"org_name": "Valid Co", "contact_name": "Someone", "contact_email": "s@valid.org"},
    ]
    results = import_wizard.commit_rows(rows)

    assert results[0]["status"] == "error"
    assert results[0]["error"]
    assert results[1]["status"] == "created"
    # The bad row created nothing; the good row did.
    assert Organization.objects.filter(name="Valid Co").exists()
    assert not Contact.objects.filter(email="n@x.org").exists()


@pytest.mark.django_db
def test_commit_rows_reuses_existing_org():
    Organization.objects.create(name="Rockefeller")
    rows = [{"org_name": "rockefeller", "contact_name": "New Person", "contact_email": "new@r.org"}]
    results = import_wizard.commit_rows(rows)
    assert results[0]["status"] == "created"
    assert Organization.objects.filter(name__iexact="rockefeller").count() == 1
