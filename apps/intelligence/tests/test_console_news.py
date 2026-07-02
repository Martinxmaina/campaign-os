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


@pytest.fixture
def ws_client(db, organization, workspace):
    """A logged-in client whose user resolves to a workspace (so news_draft,
    which now drafts via generation + persists a Post, has a workspace)."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    u = User.objects.create_user(
        email="newsdraft@x.io", password="pw", name="NewsDraft",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(
        user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER
    )
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    c = Client()
    c.force_login(u)
    return c


@pytest.mark.django_db
def test_news_draft_generates_post_and_redirects(ws_client, workspace, monkeypatch):
    """news_draft now drafts via the DeepSeek generation brain (not HERALD) and
    persists the result as a Django draft Post, then redirects to approvals."""
    from apps.composer import generation
    from apps.composer.models import Post

    captured = {}

    def fake_generate(*, workspace, user_prompt, voice="joseph", channels=None, history=None):
        captured["prompt"] = user_prompt
        captured["voice"] = voice
        return {"reply": "ok", "title": "AfDB backs Kenya grid expansion",
                "master_html": "<p>A multi-year energy-transition investment.</p>",
                "sources": ["Wiki: Energy"], "source": "deepseek"}

    monkeypatch.setattr(generation, "generate_content", fake_generate)
    resp = ws_client.post(
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
    assert "AfDB backs Kenya grid expansion" in captured["prompt"]
    post = Post.objects.filter(workspace=workspace, title="AfDB backs Kenya grid expansion").first()
    assert post is not None
    assert "multi-year energy-transition" in post.caption


@pytest.mark.django_db
def test_news_draft_never_500s_without_workspace(logged_client):
    """With no resolved workspace, news_draft still redirects cleanly (no draft,
    no 500) — the generation/persist block is skipped."""
    resp = logged_client.post(
        "/console/news/draft",
        {"sector": "Renewable power transition", "title": "Headline"},
    )
    assert resp.status_code == 302
    assert resp.url == "/console/approvals"
