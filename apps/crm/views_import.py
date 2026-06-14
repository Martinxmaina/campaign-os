"""CRM import wizard — the 4 step views (upload → map → preview → commit).

Each step is a server-rendered HTMX exchange:

  GET  /crm/import/          → ``import_home``    : the upload form (step 1)
  POST /crm/import/upload/   → ``import_upload``  : parse the file/sheet, persist a
                               CrmImportJob, render the mapping step (step 2)
  POST /crm/import/map/      → ``import_map``     : store the header→field mapping,
                               run dedup, render the preview (step 3)
  POST /crm/import/commit/   → ``import_commit``  : create rows, render the result
                               page + a per-row error report (step 4)
  GET  /crm/import/<id>/errors.csv → ``import_errors`` : download the error report.

Every view is gated by ``_can_manage_crm`` (staff or an owner/admin/campaign_owner
workspace role). The parsed rows are stashed in the Django session keyed by the
job id so steps 3/4 don't need to re-upload the file (the CrmImportJob carries
the durable metadata: source/filename/mapping/status/results).

A failed row is NEVER silently dropped — ``commit_rows`` returns a per-row result
list which we persist on the job and expose as a downloadable CSV error report.
"""
from __future__ import annotations

import csv
import io

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.crm import import_wizard
from apps.crm.models import CrmImportJob

_SESSION_ROWS_KEY = "crm_import_rows"  # {job_id: [row dict, ...]}


def _can_manage_crm(request) -> bool:
    """Gate for the CRM surfaces — staff (superuser escape hatch) OR a workspace
    role of owner/admin/campaign_owner (reusing the membership RBACMiddleware
    already resolved on the request). Mirrors ``joseph._can_access_joseph``."""
    if getattr(request.user, "is_staff", False):
        return True
    m = getattr(request, "workspace_membership", None)
    return bool(m and m.workspace_role in ("owner", "admin", "campaign_owner"))


def _stash_rows(request, job_id, rows) -> None:
    store = request.session.get(_SESSION_ROWS_KEY) or {}
    store[str(job_id)] = rows
    request.session[_SESSION_ROWS_KEY] = store
    request.session.modified = True


def _load_rows(request, job_id) -> list[dict]:
    store = request.session.get(_SESSION_ROWS_KEY) or {}
    return store.get(str(job_id)) or []


# ---------------------------------------------------------------------------
# Step 1 — upload form
# ---------------------------------------------------------------------------


@login_required
def import_home(request):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM import wizard is not available for your role.")
    return render(request, "crm/import/upload.html", {"crm_fields": import_wizard.CRM_FIELDS})


# ---------------------------------------------------------------------------
# Step 2 — upload a file / sheet URL → mapping step
# ---------------------------------------------------------------------------


@login_required
@require_POST
def import_upload(request):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM import wizard is not available for your role.")

    upload = request.FILES.get("file")
    sheet_url = (request.POST.get("sheet_url") or "").strip()

    try:
        if upload is not None:
            rows = import_wizard.parse_rows(upload.read(), upload.name)
            source = CrmImportJob.Source.FILE
            filename = upload.name
            sheet = ""
        elif sheet_url:
            rows = import_wizard.parse_sheet_url(sheet_url)
            source = CrmImportJob.Source.SHEET
            filename = ""
            sheet = sheet_url
        else:
            return render(
                request,
                "crm/import/upload.html",
                {"crm_fields": import_wizard.CRM_FIELDS,
                 "error": "Choose a .csv/.xlsx file or paste a Google Sheet URL."},
            )
    except ValueError as exc:
        return render(
            request,
            "crm/import/upload.html",
            {"crm_fields": import_wizard.CRM_FIELDS, "error": str(exc)},
        )

    headers = list(rows[0].keys()) if rows else []
    job = CrmImportJob.objects.create(
        workspace=getattr(request, "workspace", None),
        source=source,
        filename=filename,
        sheet_url=sheet,
        row_count=len(rows),
        status=CrmImportJob.Status.UPLOADED,
    )
    _stash_rows(request, job.id, rows)

    return render(
        request,
        "crm/import/map.html",
        {"job": job, "headers": headers, "crm_fields": import_wizard.CRM_FIELDS, "row_count": len(rows)},
    )


# ---------------------------------------------------------------------------
# Step 3 — store mapping → preview (new vs matched)
# ---------------------------------------------------------------------------


@login_required
@require_POST
def import_map(request):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM import wizard is not available for your role.")

    job = get_object_or_404(CrmImportJob, id=request.POST.get("job_id"))
    # Build the mapping from the per-header ``map_<header>`` form fields.
    mapping = {}
    for key, value in request.POST.items():
        if key.startswith("map_") and value:
            mapping[key[len("map_"):]] = value
    job.mapping = mapping
    job.status = CrmImportJob.Status.PREVIEWED
    job.save(update_fields=["mapping", "status", "updated_at"])

    rows = _load_rows(request, job.id)
    mapped = import_wizard.apply_mapping(rows, mapping)
    new, matched = import_wizard.dedupe(mapped)
    _stash_rows(request, job.id, rows)  # keep them for the commit step

    return render(
        request,
        "crm/import/preview.html",
        {
            "job": job,
            "new_rows": new,
            "matched_rows": matched,
            "new_count": len(new),
            "matched_count": len(matched),
        },
    )


# ---------------------------------------------------------------------------
# Step 4 — commit → result + error report
# ---------------------------------------------------------------------------


@login_required
@require_POST
def import_commit(request):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM import wizard is not available for your role.")

    job = get_object_or_404(CrmImportJob, id=request.POST.get("job_id"))
    rows = _load_rows(request, job.id)
    mapped = import_wizard.apply_mapping(rows, job.mapping)
    new, _matched = import_wizard.dedupe(mapped)

    results = import_wizard.commit_rows(new)
    created = [r for r in results if r.get("status") == "created"]
    errors = [r for r in results if r.get("status") == "error"]

    # Committed even with per-row errors — partial success is reported, not
    # rolled back (each row commits in its own transaction in commit_rows).
    job.results = results
    job.status = CrmImportJob.Status.COMMITTED
    job.save(update_fields=["results", "status", "updated_at"])

    return render(
        request,
        "crm/import/result.html",
        {
            "job": job,
            "created_count": len(created),
            "error_count": len(errors),
            "errors": errors,
        },
    )


# ---------------------------------------------------------------------------
# Error report download
# ---------------------------------------------------------------------------


@login_required
def import_errors(request, job_id):
    if not _can_manage_crm(request):
        return HttpResponseForbidden("The CRM import wizard is not available for your role.")

    job = get_object_or_404(CrmImportJob, id=job_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["error", "row"])
    for r in job.results or []:
        if r.get("status") == "error":
            writer.writerow([r.get("error", ""), r.get("row", "")])

    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="import-errors-{job.id}.csv"'
    return resp
