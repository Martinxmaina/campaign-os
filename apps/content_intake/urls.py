from django.urls import path

from apps.content_intake import views

app_name = "content_intake"

urlpatterns = [
    path("intake/", views.board, name="board"),
    path("intake/conditions/<uuid:condition_pk>/close/", views.close_condition, name="close_condition"),
    # NOTE: manual intake is wired under the live `console` namespace
    # (config/console_urls.py → console:intake-manual), not here — this URLconf
    # is not included in the root urls. See that file.
]
