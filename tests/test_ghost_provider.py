import httpx
from providers.ghost import GhostProvider
from providers.types import AuthType, PublishContent

CREDS = {"admin_api_key": "id123:" + "ab" * 32, "base_url": "https://demo.ghost.io"}


def _provider():
    return GhostProvider(credentials=dict(CREDS))


def test_auth_type_is_api_key():
    assert _provider().auth_type == AuthType.API_KEY


def test_publish_as_post_hits_posts_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(201, json={"posts": [{"id": "p1", "url": "https://demo.ghost.io/p1/"}]})

    monkeypatch.setattr("providers.ghost.httpx.post", fake_post)
    res = _provider().publish_post(
        "unused",
        PublishContent(text="Hello body", extra={"title": "My Brief", "ghost_publish_as": "post"}),
    )
    assert res.platform_post_id == "p1"
    assert "/ghost/api/admin/posts/?source=html" in captured["url"]
    assert "newsletter=" not in captured["url"]
    assert captured["json"]["posts"][0]["title"] == "My Brief"
    assert captured["headers"]["Authorization"].startswith("Ghost ")


def test_get_profile_validates_key(monkeypatch):
    monkeypatch.setattr(
        "providers.ghost.httpx.get",
        lambda url, headers=None, **kw: httpx.Response(
            200, json={"site": {"title": "Nexus Brief", "url": "https://demo.ghost.io"}}
        ),
    )
    prof = _provider().get_profile("unused")
    assert prof.name == "Nexus Brief"


def test_newsletter_mode_email_only(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(201, json={"posts": [{"id": "n1", "url": "https://demo.ghost.io/n1/"}]})

    monkeypatch.setattr("providers.ghost.httpx.post", fake_post)
    creds = dict(CREDS)
    creds["newsletter_slug"] = "weekly"
    res = GhostProvider(credentials=creds).publish_post(
        "x",
        PublishContent(text="Body", extra={"title": "T", "ghost_publish_as": "newsletter"}),
    )
    assert res.platform_post_id == "n1"
    assert "newsletter=weekly" in captured["url"]
    assert captured["json"]["posts"][0]["email_only"] is True


def test_newsletter_without_slug_fails():
    import pytest
    from providers.exceptions import PublishError

    with pytest.raises(PublishError):
        GhostProvider(credentials=dict(CREDS)).publish_post(
            "x",
            PublishContent(text="B", extra={"ghost_publish_as": "newsletter"}),
        )
