from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render


def health_check(request):
    """Health check endpoint at /health/."""
    return JsonResponse({"status": "ok"})


@login_required
def dashboard(request):
    """Main dashboard - redirects to last used workspace or shows org overview."""
    from apps.members.models import WorkspaceMembership

    user = request.user
    if user.last_workspace_id:
        return redirect("workspaces:detail", workspace_id=user.last_workspace_id)

    # Fallback: try to find any workspace the user belongs to
    membership = (
        WorkspaceMembership.objects.filter(user=user, workspace__is_archived=False).select_related("workspace").first()
    )
    if membership:
        user.last_workspace_id = membership.workspace.id
        user.save(update_fields=["last_workspace_id"])
        return redirect("workspaces:detail", workspace_id=membership.workspace.id)

    return render(request, "accounts/dashboard.html")


@login_required
def account_settings(request):
    tab = request.GET.get("tab", "profile")
    settings_active = "preferences" if tab == "preferences" else "profile"
    return render(request, "accounts/settings.html", {"settings_active": settings_active})


def logout_view(request):
    logout(request)
    return redirect("account_login")
