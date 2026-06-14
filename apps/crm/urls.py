"""CRM routes — mounted at ``/crm/`` (see ``config/urls.py``).

Task 6 adds the 4-step import wizard; later tasks (7, 8, 10) extend this file with
the organizations/contacts CRUD, thread CRUD, and final nav routes.
"""
from django.urls import path

from apps.crm import views_import

app_name = "crm"

urlpatterns = [
    # Import wizard — upload → map → preview → commit (+ error report download).
    path("import/", views_import.import_home, name="import-home"),
    path("import/upload/", views_import.import_upload, name="import-upload"),
    path("import/map/", views_import.import_map, name="import-map"),
    path("import/commit/", views_import.import_commit, name="import-commit"),
    path("import/<uuid:job_id>/errors.csv", views_import.import_errors, name="import-errors"),
]
