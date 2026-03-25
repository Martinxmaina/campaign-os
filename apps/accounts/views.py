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
    user = request.user
    if user.last_workspace_id:
        return redirect("workspaces:detail", workspace_id=user.last_workspace_id)
    return render(request, "accounts/dashboard.html")


@login_required
def account_settings(request):
    return render(request, "accounts/settings.html")


def logout_view(request):
    logout(request)
    return redirect("account_login")
