from django.urls import path

from . import views

app_name = "settings_manager"

urlpatterns = [
    path("", views.settings_index, name="index"),
    path("intake/save/", views.save_intake_settings, name="save_intake_settings"),
]
