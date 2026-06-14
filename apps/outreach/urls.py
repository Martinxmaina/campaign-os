"""Outreach routes — mounted at ``/outreach/`` (see ``config/urls.py``).

Task 7 adds the mailbox connect/status surface; later tasks (8) extend this file
with thread send + sequence enroll + triage + suppression + the public
unsubscribe view.
"""
from django.urls import path

from apps.outreach import views

app_name = "outreach"

urlpatterns = [
    # Mailbox connect / status dashboard + pause/resume controls.
    path("mailbox/", views.mailbox_status, name="mailbox"),
    path("mailbox/<uuid:mailbox_id>/pause/", views.mailbox_pause, name="mailbox-pause"),
    path("mailbox/<uuid:mailbox_id>/resume/", views.mailbox_resume, name="mailbox-resume"),
]
