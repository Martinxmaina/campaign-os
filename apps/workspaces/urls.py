from django.urls import path

from . import views

app_name = "workspaces"

urlpatterns = [
    path("", views.workspace_list, name="list"),
    path("<uuid:workspace_id>/", views.detail, name="detail"),
]
