from django.urls import path

from apps.content_intake import views

app_name = "content_intake"

urlpatterns = [
    path("intake/", views.board, name="board"),
    path("intake/conditions/<uuid:condition_pk>/close/", views.close_condition, name="close_condition"),
]
