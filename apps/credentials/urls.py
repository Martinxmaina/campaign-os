from django.urls import path

from . import views

app_name = "credentials"

urlpatterns = [
    path("", views.credentials_list, name="list"),
    path("connect/ghost/", views.connect_ghost, name="connect-ghost"),
    path("<str:platform>/save/", views.save_credential, name="save"),
    path("<str:platform>/delete/", views.delete_credential, name="delete"),
]
