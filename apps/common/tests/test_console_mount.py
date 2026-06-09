import pytest
from django.test import Client


@pytest.mark.django_db
def test_console_home_redirects_to_login_when_anonymous():
    resp = Client().get("/console/")
    assert resp.status_code in (302, 301)
    assert "/login" in resp.headers.get("Location", "") or "/accounts/login" in resp.headers.get("Location", "")
