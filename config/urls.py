from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health_check"),
    path("accounts/", include("apps.accounts.urls")),
    path("accounts/", include("allauth.urls")),
    path("organizations/", include("apps.organizations.urls")),
    path("workspaces/", include("apps.workspaces.urls")),
    path("members/", include("apps.members.urls")),
    path("settings/", include("apps.settings_manager.urls")),
    path("credentials/", include("apps.credentials.urls")),
    # Content Pipeline (Stream A)
    path("workspace/<uuid:workspace_id>/", include("apps.composer.urls")),
    path("workspace/<uuid:workspace_id>/calendar/", include("apps.calendar.urls")),
    path("", include("apps.accounts.urls_root")),
]
