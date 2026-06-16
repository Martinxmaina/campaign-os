"""Daily CRM→Google Sheet pipeline mirror (write to a dedicated tab)."""
from unittest.mock import MagicMock

import pytest


def _fake_service(existing_tabs):
    svc = MagicMock()
    svc.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"title": t}} for t in existing_tabs]
    }
    return svc


@pytest.mark.django_db
def test_mirror_writes_pipeline_to_dedicated_tab(settings):
    from apps.crm.models import Organization, OutreachThread
    from apps.crm.sheet_mirror import mirror_pipeline_to_sheet

    settings.CRM_TRACKER_SHEET_ID = "sheet123"
    settings.CRM_TRACKER_TAB = "Campaign OS — Pipeline"
    org = Organization.objects.create(name="Rockefeller")
    OutreachThread.objects.create(org=org, stage="proposal_sent", traffic_light="red",
                                  quintile=4, next_action="Follow up")

    svc = _fake_service(existing_tabs=["README", "My Projects", "Lookups"])
    result = mirror_pipeline_to_sheet(service=svc)

    assert result["rows"] == 1 and result["tab"] == "Campaign OS — Pipeline"
    # created the dedicated tab (it wasn't in the existing tabs) — never the user's tabs
    svc.spreadsheets.return_value.batchUpdate.assert_called_once()
    # cleared + wrote the values
    svc.spreadsheets.return_value.values.return_value.clear.assert_called_once()
    update = svc.spreadsheets.return_value.values.return_value.update
    update.assert_called_once()
    written = update.call_args.kwargs["body"]["values"]
    assert written[0][0] == "Org"                       # header
    assert any("Rockefeller" in r for r in written[1:])  # the thread row


@pytest.mark.django_db
def test_mirror_skips_when_no_sheet_configured(settings):
    from apps.crm.sheet_mirror import mirror_pipeline_to_sheet
    settings.CRM_TRACKER_SHEET_ID = ""
    assert mirror_pipeline_to_sheet(service=MagicMock()) == {"skipped": "no-sheet-configured"}


@pytest.mark.django_db
def test_mirror_does_not_recreate_existing_tab(settings):
    from apps.crm.sheet_mirror import mirror_pipeline_to_sheet
    settings.CRM_TRACKER_SHEET_ID = "sheet123"
    settings.CRM_TRACKER_TAB = "Campaign OS — Pipeline"
    svc = _fake_service(existing_tabs=["Campaign OS — Pipeline"])  # already there
    mirror_pipeline_to_sheet(service=svc)
    svc.spreadsheets.return_value.batchUpdate.assert_not_called()  # no addSheet
