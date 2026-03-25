from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from apps.members.models import WorkspaceMembership

from .models import Workspace


@login_required
def detail(request, workspace_id):
    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        raise Http404 from None

    # Verify user has access
    if not WorkspaceMembership.objects.filter(
        user=request.user, workspace=workspace
    ).exists():
        raise Http404

    # Persist last used workspace
    request.user.last_workspace_id = workspace.id
    request.user.save(update_fields=["last_workspace_id"])

    return render(request, "workspaces/detail.html", {"workspace": workspace})


@login_required
def workspace_list(request):
    memberships = WorkspaceMembership.objects.filter(user=request.user).select_related("workspace")
    workspaces = [m.workspace for m in memberships if not m.workspace.is_archived]
    return render(request, "workspaces/list.html", {"workspaces": workspaces})
