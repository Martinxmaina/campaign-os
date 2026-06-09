import pytest
from django.test import Client
from django.contrib.auth import get_user_model
from django.utils import timezone


@pytest.fixture
def logged_client(db):
    User = get_user_model()
    u = User.objects.create_user(
        email="op3@x.io", password="pw", name="Op3", tos_accepted_at=timezone.now()
    )
    c = Client()
    c.force_login(u)
    return c


@pytest.mark.django_db
def test_pipeline_groups_by_traffic_light(logged_client, monkeypatch):
    from apps.intelligence import console_views
    monkeypatch.setattr(console_views, "safe_get",
                        lambda path, default: {"items": [
                            {"id": "t1", "subject": "AfDB", "org": "AfDB", "owner": "joseph",
                             "traffic_light": "red", "quintile": 5, "next_action": "call"}]})
    resp = logged_client.get("/console/pipeline")
    assert resp.status_code == 200 and b"AfDB" in resp.content


@pytest.mark.django_db
def test_notification_read_posts(logged_client, monkeypatch):
    from apps.intelligence import console_views
    calls = {}
    monkeypatch.setattr(console_views, "agent_post",
                        lambda path, json=None: calls.setdefault("path", path) or {})
    resp = logged_client.post("/console/notifications/n1/read")
    assert resp.status_code in (302, 303) and calls["path"] == "/notifications/n1/read"
