from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("settings/", views.account_settings, name="settings"),
    path("logout/", views.logout_view, name="logout"),
]
