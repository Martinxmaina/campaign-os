"""Tests for the 4-step CRM import wizard views (upload → map → preview → commit).

The wizard lets a campaign_owner/admin/owner pull a spreadsheet of funders into
the canonical Django CRM. Each step is gated by ``_can_manage_crm`` (staff or an
owner/admin/campaign_owner workspace role), CSP-safe (no inline handlers — Alpine
``@click`` + ``hx-*`` only), and a failed row never silently drops: the result
page surfaces a per-row, downloadable error report.

Flow under test:
  GET  /crm/import/          → 200 upload form (gated; 403 for a viewer)
  POST /crm/import/upload/   → 200 mapping step listing the uploaded headers
  POST /crm/import/map/      → 200 preview step (new vs matched counts)
  POST /crm/import/commit/   → 200 result page (created count + error report)
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


CSV_BYTES = (
    b"Org,Name,Email,Stage,Track\n"
    b"Rockefeller,Dr. Okonkwo,okonkwo@rockefeller.org,engaged,ai10bn\n"
    b"GEAPP,Jane Doe,jane@geapp.org,targeted,energy\n"
)

# A CSV whose second row has no org name → must become an error, never a crash.
CSV_WITH_BAD_ROW = (
    b"Org,Name,Email\n"
    b"GIZ,Hans Schmidt,hans@giz.de\n"
    b",Nobody,nobody@nowhere.org\n"
)


@pytest.fixture
def manager(client, org_owner, workspace):
    """A workspace owner — passes ``_can_manage_crm``."""
    from apps.members.models import WorkspaceMembership

    WorkspaceMembership.objects.create(
        user=org_owner, workspace=workspace, workspace_role="owner"
    )
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def campaign_owner(client, db, organization, workspace):
    """A campaign_owner — also passes the gate."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from django.utils import timezone

    u = User.objects.create_user(
        email="campaign@example.com", password="x", name="Campaign Owner",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(
        user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER
    )
    WorkspaceMembership.objects.create(
        user=u, workspace=workspace, workspace_role="campaign_owner"
    )
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


@pytest.fixture
def viewer(client, db, organization, workspace):
    """An ordinary member (viewer) — must be 403'd from the wizard."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from django.utils import timezone

    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(
        user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER
    )
    WorkspaceMembership.objects.create(
        user=u, workspace=workspace, workspace_role="member"
    )
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


def _upload_csv(client, data=CSV_BYTES, filename="funders.csv"):
    import io

    f = io.BytesIO(data)
    f.name = filename
    return client.post(reverse("crm:import-upload"), {"file": f})


# ---------------------------------------------------------------------------
# Step 1 — upload form + role gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_upload_form_renders_for_manager(manager, client):
    resp = client.get(reverse("crm:import-home"))
    assert resp.status_code == 200
    # CSP-safe: no inline event handlers in the rendered HTML.
    body = resp.content.decode()
    assert "onclick=" not in body
    assert "onsubmit=" not in body


@pytest.mark.django_db
def test_upload_form_renders_for_campaign_owner(campaign_owner, client):
    resp = client.get(reverse("crm:import-home"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_upload_form_forbidden_for_viewer(viewer, client):
    resp = client.get(reverse("crm:import-home"))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Step 2 — upload a CSV → mapping step lists the headers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_csv_renders_mapping_step_with_headers(manager, client):
    resp = _upload_csv(client)
    assert resp.status_code == 200
    body = resp.content.decode()
    # The wizard lists the source headers so the user can map each one.
    for header in ("Org", "Name", "Email", "Stage", "Track"):
        assert header in body
    # A CrmImportJob was persisted for this workspace.
    from apps.crm.models import CrmImportJob

    assert CrmImportJob.objects.count() == 1
    job = CrmImportJob.objects.first()
    assert job.filename == "funders.csv"
    assert job.status == CrmImportJob.Status.UPLOADED


@pytest.mark.django_db
def test_post_csv_forbidden_for_viewer(viewer, client):
    resp = _upload_csv(client)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Step 3 — map step → preview with new vs matched counts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_map_renders_preview_with_new_and_matched_counts(manager, client):
    # Pre-seed a matching org+contact so one of the two CSV rows is "matched".
    from apps.crm.models import Contact, Organization

    org = Organization.objects.create(name="Rockefeller")
    Contact.objects.create(org=org, full_name="Dr. Okonkwo", email="okonkwo@rockefeller.org")

    _upload_csv(client)
    from apps.crm.models import CrmImportJob

    job = CrmImportJob.objects.first()
    mapping = {
        "Org": "org_name",
        "Name": "contact_name",
        "Email": "contact_email",
        "Stage": "stage",
        "Track": "track",
    }
    resp = client.post(
        reverse("crm:import-map"),
        {"job_id": str(job.id), **{f"map_{k}": v for k, v in mapping.items()}},
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    # One row matches the seeded contact, one is new.
    assert "1" in body  # matched count
    assert "GEAPP" in body  # the new row's org shows in the preview
    job.refresh_from_db()
    assert job.mapping == mapping
    assert job.status == CrmImportJob.Status.PREVIEWED


# ---------------------------------------------------------------------------
# Step 4 — commit → result page with created count + error report
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_commit_creates_rows_and_renders_result(manager, client):
    _upload_csv(client)
    from apps.crm.models import CrmImportJob, OutreachThread

    job = CrmImportJob.objects.first()
    job.mapping = {"Org": "org_name", "Name": "contact_name", "Email": "contact_email"}
    job.save(update_fields=["mapping"])

    resp = client.post(reverse("crm:import-commit"), {"job_id": str(job.id)})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "2" in body  # two created
    assert OutreachThread.objects.count() == 2
    job.refresh_from_db()
    assert job.status == CrmImportJob.Status.COMMITTED
    assert len(job.results) == 2


@pytest.mark.django_db
def test_commit_with_bad_row_surfaces_error_report(manager, client):
    _upload_csv(client, data=CSV_WITH_BAD_ROW, filename="bad.csv")
    from apps.crm.models import CrmImportJob, OutreachThread

    job = CrmImportJob.objects.first()
    job.mapping = {"Org": "org_name", "Name": "contact_name", "Email": "contact_email"}
    job.save(update_fields=["mapping"])

    resp = client.post(reverse("crm:import-commit"), {"job_id": str(job.id)})
    assert resp.status_code == 200
    body = resp.content.decode()
    # One row created, one failed — the error is surfaced, never silently dropped.
    assert "missing org_name" in body
    assert OutreachThread.objects.count() == 1
    # A downloadable error report link/button is present.
    assert reverse("crm:import-errors", args=[job.id]) in body


@pytest.mark.django_db
def test_error_report_download_is_csv(manager, client):
    _upload_csv(client, data=CSV_WITH_BAD_ROW, filename="bad.csv")
    from apps.crm.models import CrmImportJob

    job = CrmImportJob.objects.first()
    job.mapping = {"Org": "org_name", "Name": "contact_name", "Email": "contact_email"}
    job.save(update_fields=["mapping"])
    client.post(reverse("crm:import-commit"), {"job_id": str(job.id)})

    resp = client.get(reverse("crm:import-errors", args=[job.id]))
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert b"missing org_name" in resp.content


@pytest.mark.django_db
def test_commit_forbidden_for_viewer(viewer, client, workspace):
    # A viewer can't even reach commit even with a fabricated job id.
    from apps.crm.models import CrmImportJob

    job = CrmImportJob.objects.create(workspace=workspace, filename="x.csv")
    resp = client.post(reverse("crm:import-commit"), {"job_id": str(job.id)})
    assert resp.status_code == 403
