import pytest
from django.test import Client
from django.contrib.auth import get_user_model
from django.utils import timezone


@pytest.fixture
def logged_client(db):
    User = get_user_model()
    u = User.objects.create_user(
        email="op4@x.io", password="pw", name="Op4", tos_accepted_at=timezone.now()
    )
    c = Client(); c.force_login(u); return c


@pytest.mark.django_db
def test_graph_json_proxies_agent_graph(logged_client, monkeypatch):
    from apps.intelligence import console_views
    monkeypatch.setattr(console_views, "safe_get",
                        lambda path, default: {"nodes": [{"id": "wiki:afdb", "type": "wiki", "label": "AfDB", "meta": {}}],
                                               "edges": []})
    resp = logged_client.get("/console/graph.json")
    assert resp.status_code == 200
    assert resp.json()["nodes"][0]["type"] == "wiki"


@pytest.mark.django_db
def test_brain_page_renders(logged_client):
    resp = logged_client.get("/console/brain")
    assert resp.status_code == 200 and b"force-graph" in resp.content
