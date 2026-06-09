import pytest
from django.test import Client
from django.contrib.auth import get_user_model
from django.utils import timezone


@pytest.fixture
def logged_client(db):
    User = get_user_model()
    u = User.objects.create_user(
        email="op@x.io", password="pw", name="Op", tos_accepted_at=timezone.now()
    )
    c = Client()
    c.force_login(u)
    return c


@pytest.mark.django_db
def test_ideas_page_renders_agent_data(logged_client, monkeypatch):
    from apps.composer import console_views
    monkeypatch.setattr(console_views, "safe_get",
                        lambda path, default: {"items": [
                            {"id": "i1", "title": "Energy brief", "sector": "energy", "rank": 1,
                             "score": 0.8, "status": "proposed", "rationale": {"why": "fresh"}}]})
    resp = logged_client.get("/console/ideas")
    assert resp.status_code == 200
    assert b"Energy brief" in resp.content


@pytest.mark.django_db
def test_decide_posts_to_agent(logged_client, monkeypatch):
    from apps.composer import console_views
    calls = {}
    monkeypatch.setattr(console_views, "agent_post",
                        lambda path, json=None: calls.setdefault("path", path) or {"status": "accepted"})
    resp = logged_client.post("/console/ideas/i1/decide", {"decision": "accept"})
    assert resp.status_code in (302, 303)
    assert calls["path"] == "/ideas/i1/decide"
