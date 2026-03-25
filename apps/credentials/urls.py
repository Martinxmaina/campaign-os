from django.urls import path

from . import views

app_name = "credentials"

urlpatterns = [
    path("", views.credentials_list, name="list"),
]
