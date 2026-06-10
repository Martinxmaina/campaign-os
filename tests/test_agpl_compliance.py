import pytest
from django.test import Client


@pytest.mark.django_db
def test_footer_has_source_link():
    resp = Client().get("/")
    assert resp.status_code in (200, 302)
    if resp.status_code == 200:
        body = resp.content.decode().lower()
        assert "source" in body  # footer "Source" link present


@pytest.mark.django_db
def test_about_page_exposes_notice():
    resp = Client().get("/about/")
    assert resp.status_code == 200
    assert "modified version of campaign os" in resp.content.decode().lower()
