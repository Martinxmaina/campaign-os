"""Public (no-auth) outreach routes — mounted top-level in ``config/urls.py``.

Only the unsubscribe view lives here: a recipient must be able to opt out without
an account, so it sits at ``/unsubscribe/<token>/`` (matching the URL that
``senders._unsubscribe_url`` mints into the email footer + ``List-Unsubscribe``
header).

It uses its OWN ``outreach_public`` namespace rather than ``outreach``: Django
binds a shared app-namespace to a single instance, so a second include declaring
``app_name = "outreach"`` would be shadowed (only the ``/outreach/`` mount would
be reverse-able). Keeping it distinct makes ``reverse("outreach_public:unsubscribe")``
resolve to the public ``/unsubscribe/<token>/`` path, which is what the email
footer links to.
"""
from django.urls import path

from apps.outreach import views_thread

app_name = "outreach_public"

urlpatterns = [
    path("unsubscribe/<str:token>/", views_thread.unsubscribe, name="unsubscribe"),
]
