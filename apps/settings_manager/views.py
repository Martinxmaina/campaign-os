from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.settings_manager.helpers import get_org_setting, set_org_setting


def _get_org(request):
    ws = getattr(request, "workspace", None)
    if ws:
        return ws.organization
    membership = request.user.org_memberships.select_related("organization").first()
    return membership.organization if membership else None


def _can_manage_settings(request):
    org = _get_org(request)
    if not org:
        return False
    membership = request.user.org_memberships.filter(organization=org).first()
    if membership and membership.org_role in ("owner", "admin"):
        return True
    ws = getattr(request, "workspace", None)
    if ws:
        ws_membership = request.user.workspace_memberships.filter(workspace=ws).first()
        if ws_membership and ws_membership.workspace_role in ("owner", "admin", "campaign_owner"):
            return True
    return False


@login_required
def settings_index(request):
    org = _get_org(request)
    can_manage = _can_manage_settings(request)

    intake_sheet_id = (get_org_setting(org.pk, "intake.sheet_id") or "") if org else ""
    intake_sheet_range = (get_org_setting(org.pk, "intake.sheet_range") or "Sheet1!A:P") if org else "Sheet1!A:P"
    intake_sync_enabled = get_org_setting(org.pk, "intake.sync_enabled") if org else True

    return render(request, "settings_manager/index.html", {
        "can_manage": can_manage,
        "intake_sheet_id": intake_sheet_id,
        "intake_sheet_range": intake_sheet_range,
        "intake_sync_enabled": intake_sync_enabled,
    })


@login_required
@require_POST
def save_intake_settings(request):
    if not _can_manage_settings(request):
        messages.error(request, "You don't have permission to change these settings.")
        return redirect("settings_manager:index")

    org = _get_org(request)
    if not org:
        messages.error(request, "No organisation found.")
        return redirect("settings_manager:index")

    sheet_id = request.POST.get("intake_sheet_id", "").strip()
    sheet_range = request.POST.get("intake_sheet_range", "Sheet1!A:P").strip() or "Sheet1!A:P"
    sync_enabled = request.POST.get("intake_sync_enabled") == "on"

    set_org_setting(org.pk, "intake.sheet_id", sheet_id)
    set_org_setting(org.pk, "intake.sheet_range", sheet_range)
    set_org_setting(org.pk, "intake.sync_enabled", sync_enabled)

    messages.success(request, "Content intake settings saved.")
    return redirect("settings_manager:index")
