import pytest
from django.test import Client
from django.contrib.auth import get_user_model
from django.utils import timezone


@pytest.fixture
def logged_client(db):
    User = get_user_model()
    u = User.objects.create_user(
        email="news@x.io", password="pw", name="NewsOp", tos_accepted_at=timezone.now()
    )
    c = Client()
    c.force_login(u)
    return c


_DIGEST = {
    "items": [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "title": "AfDB backs Kenya grid expansion",
            "summary": "A multi-year energy-transition investment across East Africa.",
            "link": "https://esi-africa.com/kenya-grid",
            "source": "ESI Africa",
            "published_at": "2026-06-10T08:00:00Z",
            "sector": "energy",
            "africa": True,
            "score": 0.87,
            "rationale": "AfDB-backed grid expansion in Kenya — direct energy relevance.",
            "run_date": "2026-06-10",
            "status": "new",
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "title": "Global AI model release",
            "summary": "A new foundation model launches worldwide.",
            "link": "https://restofworld.org/ai-model",
            "source": "Rest of World",
            "published_at": None,
            "sector": "ai",
            "africa": False,
            "score": 0.55,
            "rationale": "(heuristic match)",
            "run_date": "2026-06-10",
            "status": "new",
        },
    ],
    "counts": {"total": 2, "by_sector": {"energy": 1, "ai": 1}, "africa": 1},
    "generated_at": "2026-06-10T05:00:00Z",
}


@pytest.mark.django_db
def test_news_renders_items_with_badges_and_rationale(logged_client, monkeypatch):
    from apps.intelligence import console_views

    monkeypatch.setattr(console_views, "safe_get", lambda path, default: _DIGEST)
    resp = logged_client.get("/console/news")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "AfDB backs Kenya grid expansion" in body
    assert "ESI Africa" in body
    assert "energy" in body
    # Africa badge present for the africa=True item
    assert "🌍" in body
    # rationale rendered
    assert "AfDB-backed grid expansion in Kenya" in body
    assert "(heuristic match)" in body
    # external source link
    assert "https://esi-africa.com/kenya-grid" in body
    # Draft with HERALD action
    assert "Draft with HERALD" in body


@pytest.mark.django_db
def test_news_passes_filters_to_querystring(logged_client, monkeypatch):
    from apps.intelligence import console_views

    captured = {}

    def fake_get(path, default):
        captured["path"] = path
        return _DIGEST

    monkeypatch.setattr(console_views, "safe_get", fake_get)
    resp = logged_client.get("/console/news?sector=energy&africa=true")
    assert resp.status_code == 200
    assert captured["path"] == "/news/digest?sector=energy&africa=true"


@pytest.mark.django_db
def test_news_empty_state(logged_client, monkeypatch):
    from apps.intelligence import console_views

    monkeypatch.setattr(
        console_views,
        "safe_get",
        lambda path, default: {"items": [], "counts": {}, "generated_at": None},
    )
    resp = logged_client.get("/console/news")
    assert resp.status_code == 200
    assert b"No recommendations" in resp.content


@pytest.mark.django_db
def test_news_draft_posts_and_redirects(logged_client, monkeypatch):
    from apps.intelligence import console_views

    captured = {}

    def fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True}

    monkeypatch.setattr(console_views, "agent_post", fake_post)
    resp = logged_client.post(
        "/console/news/draft",
        {
            "sector": "energy",
            "title": "AfDB backs Kenya grid expansion",
            "summary": "A multi-year energy-transition investment.",
            "link": "https://esi-africa.com/kenya-grid",
            "source": "ESI Africa",
        },
    )
    assert resp.status_code == 302
    assert resp.url == "/console/approvals"
    assert captured["path"] == "/agents/herald/draft"
    assert captured["payload"]["sector"] == "energy"
    assert "AfDB backs Kenya grid expansion" in captured["payload"]["brief"]


@pytest.mark.django_db
def test_news_draft_normalises_freetext_sector(logged_client, monkeypatch):
    """A non-canonical request-supplied sector must be mapped to a canonical
    value before hitting the agent-service (which only accepts
    energy|agribusiness|ai|general)."""
    from apps.intelligence import console_views

    captured = {}

    def fake_post(path, payload):
        captured["payload"] = payload
        return {"ok": True}

    monkeypatch.setattr(console_views, "agent_post", fake_post)
    resp = logged_client.post(
        "/console/news/draft",
        {
            "sector": "Renewable power transition",  # free-text -> energy
            "title": "Headline",
        },
    )
    assert resp.status_code == 302
    assert captured["payload"]["sector"] == "energy"
