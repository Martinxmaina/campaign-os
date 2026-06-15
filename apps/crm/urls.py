"""CRM routes — mounted at ``/crm/`` (see ``config/urls.py``).

Task 6 added the 4-step import wizard; Task 7 adds the organizations/contacts
CRUD (list/detail/create/edit). Later tasks (8, 10) extend this file with thread
CRUD and final nav routes.
"""
from django.urls import path

from apps.crm import thread_views, views, views_import

app_name = "crm"

urlpatterns = [
    # Import wizard — upload → map → preview → commit (+ error report download).
    path("import/", views_import.import_home, name="import-home"),
    path("import/upload/", views_import.import_upload, name="import-upload"),
    path("import/map/", views_import.import_map, name="import-map"),
    path("import/commit/", views_import.import_commit, name="import-commit"),
    path("import/<uuid:job_id>/errors.csv", views_import.import_errors, name="import-errors"),
    # Organizations CRUD.
    path("orgs/", views.org_list, name="org-list"),
    path("orgs/new/", views.org_new, name="org-new"),
    path("orgs/<uuid:org_id>/", views.org_detail, name="org-detail"),
    path("orgs/<uuid:org_id>/edit/", views.org_edit, name="org-edit"),
    # Contacts CRUD.
    path("contacts/", views.contact_list, name="contact-list"),
    path("contacts/new/", views.contact_new, name="contact-new"),
    path("contacts/<uuid:contact_id>/", views.contact_detail, name="contact-detail"),
    path("contacts/<uuid:contact_id>/edit/", views.contact_edit, name="contact-edit"),
    # Team thread CRUD — the Joseph drawer posts these (edit / log activity / add task).
    path("threads/<uuid:thread_id>/edit/", thread_views.thread_edit, name="thread-edit"),
    path("threads/<uuid:thread_id>/stage/", thread_views.set_stage, name="thread-set-stage"),
    path("threads/<uuid:thread_id>/activity/", thread_views.thread_activity, name="thread-activity"),
    path("threads/<uuid:thread_id>/task/", thread_views.thread_task, name="thread-task"),
    path("threads/<uuid:thread_id>/refresh-dossier/", thread_views.refresh_dossier,
         name="thread-refresh-dossier"),
]
