import pytest
from django.test import Client
from django.contrib.auth import get_user_model
from django.utils import timezone


@pytest.fixture
def logged_client(db):
    User = get_user_model()
    u = User.objects.create_user(
        email="op2@x.io", password="pw", name="Op2", tos_accepted_at=timezone.now()
    )
    c = Client()
    c.force_login(u)
    return c


@pytest.mark.django_db
def test_ai_approvals_renders(logged_client, monkeypatch):
    from apps.approvals import console_views
    monkeypatch.setattr(console_views, "safe_get",
                        lambda path, default: {"items": [
                            {"id": "a1", "target_type": "content_item", "target_ref": "c1", "status": "pending"}]})
    resp = logged_client.get("/console/approvals")
    assert resp.status_code == 200 and b"content_item" in resp.content


@pytest.mark.django_db
def test_approval_decide_posts(logged_client, monkeypatch):
    from apps.approvals import console_views
    calls = {}
    monkeypatch.setattr(console_views, "agent_post",
                        lambda path, json=None: calls.update(path=path, json=json) or {"status": "approved"})
    resp = logged_client.post("/console/approvals/a1/decide", {"decision": "approve"})
    assert resp.status_code in (302, 303)
    assert calls["path"] == "/approvals/a1/decide" and calls["json"]["decision"] == "approve"
