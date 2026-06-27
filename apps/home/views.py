from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import services


def _can(request, key: str) -> bool:
    if getattr(request.user, "is_staff", False):
        return True
    m = getattr(request, "workspace_membership", None)
    return bool(m and m.effective_permissions.get(key, False))


@login_required
def index(request, workspace_id):
    workspace = request.workspace  # set by RBACMiddleware
    user = request.user
    is_admin = _can(request, "manage_workspace_settings")
    show_analytics = _can(request, "view_analytics")

    ctx = {
        "workspace": workspace,
        "show_analytics": show_analytics,
        "is_admin": is_admin,
        "perf": services.performance_summary(workspace) if show_analytics else None,
        "drafts": services.my_drafts(workspace, user),
        "going_out": services.going_out_soon(workspace),
        "signoff": services.pending_signoff(workspace, user) if _can(request, "approve_posts") else [],
        # can_access_joseph / can_manage_crm / sidebar_* arrive via context processors
    }
    return render(request, "home/index.html", ctx)
