"""Outreach routes — mounted at ``/outreach/`` (see ``config/urls.py``).

Task 7 adds the mailbox connect/status surface. Task 8 adds the thread send +
sequence enroll actions, the reply-triage queue, and the suppression list (all
role-gated). The *public* unsubscribe view is NOT here — it lives top-level at
``/unsubscribe/<token>/`` (see ``apps.outreach.urls_public`` + ``config/urls.py``)
so the footer/header link a recipient can hit without an account, matching the
URL ``senders._unsubscribe_url`` mints.
"""
from django.urls import path

from apps.outreach import views, views_thread

app_name = "outreach"

urlpatterns = [
    # Mailbox connect / status dashboard + pause/resume controls.
    path("mailbox/", views.mailbox_status, name="mailbox"),
    path("mailbox/<uuid:mailbox_id>/pause/", views.mailbox_pause, name="mailbox-pause"),
    path("mailbox/<uuid:mailbox_id>/resume/", views.mailbox_resume, name="mailbox-resume"),
    # Thread send (gate→guarded_send) + sequence enroll.
    path("threads/<uuid:thread_id>/send/", views_thread.thread_send, name="thread-send"),
    path("threads/<uuid:thread_id>/enroll/", views_thread.thread_enroll, name="thread-enroll"),
    # Reply-triage queue.
    path("triage/", views_thread.triage_queue, name="triage"),
    # Suppression list + add/remove.
    path("suppression/", views_thread.suppression_list, name="suppression"),
    path("suppression/add/", views_thread.suppression_add, name="suppression-add"),
    path(
        "suppression/<uuid:entry_id>/remove/",
        views_thread.suppression_remove,
        name="suppression-remove",
    ),
]
