from django.urls import path

from . import webhooks

app_name = "twg"

urlpatterns = [
    # No trailing slash — matches the fixed contract path exactly so a POST
    # is never 301-redirected (which would drop the body).
    path("twg-meeting", webhooks.twg_meeting, name="twg_meeting"),
]
