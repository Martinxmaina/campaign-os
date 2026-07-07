"""Ghost policy (2026-07): every update publishes a PUBLIC web post AND notifies
subscribers with a TEASER email that links back to it — never the full article
by email. The web post URL is authoritative (that's what [NEXUS BRIEF LINK] uses).
"""
import httpx

from providers.ghost import GhostProvider
from providers.types import PublishContent

CREDS = {"admin_api_key": "id123:" + "ab" * 32, "base_url": "https://demo.ghost.io"}


def _provider():
    return GhostProvider(credentials=dict(CREDS))


def _mock_ghost(monkeypatch, *, teaser_fails=False):
    calls = {"posts": [], "puts": []}

    def fake_post(url, headers=None, json=None, **kw):
        calls["posts"].append({"url": url, "json": json})
        if "source=html" in url and "newsletter=" not in url:
            return httpx.Response(201, json={"posts": [{"id": "web1", "url": "https://demo.ghost.io/brief/"}]})
        return httpx.Response(201, json={"posts": [{"id": "email1", "updated_at": "2026-07-07T00:00:00.000Z"}]})

    def fake_get(url, headers=None, **kw):
        return httpx.Response(200, json={"newsletters": [{"slug": "default-newsletter"}]})

    def fake_put(url, headers=None, json=None, **kw):
        calls["puts"].append({"url": url, "json": json})
        if teaser_fails:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"posts": [{"id": "email1"}]})

    monkeypatch.setattr("providers.ghost.httpx.post", fake_post)
    monkeypatch.setattr("providers.ghost.httpx.get", fake_get)
    monkeypatch.setattr("providers.ghost.httpx.put", fake_put)
    return calls


def test_publish_makes_public_post_plus_teaser_email(monkeypatch):
    calls = _mock_ghost(monkeypatch)
    body = "The full Nexus Brief article body with lots of detail about the TWG session."
    res = _provider().publish_post(
        "x", PublishContent(text=body, extra={"subtitle": "A short teaser line"})
    )

    # Web post is the authoritative result + URL.
    assert res.platform_post_id == "web1"
    assert res.url == "https://demo.ghost.io/brief/"

    web = next(c for c in calls["posts"] if "source=html" in c["url"] and "newsletter=" not in c["url"])
    wp = web["json"]["posts"][0]
    assert wp["status"] == "published"
    assert "email_only" not in wp              # public web post, NOT email-only
    assert body[:20] in wp["html"]             # full article lives on the web

    # Teaser email: email-only, links to the article, and does NOT carry the body.
    teaser = next(c for c in calls["posts"] if "newsletter=" in c["url"])
    tp = teaser["json"]["posts"][0]
    assert tp["email_only"] is True
    assert "https://demo.ghost.io/brief/" in tp["html"]
    assert "Read the full brief" in tp["html"]
    assert "A short teaser line" in tp["html"]
    assert body not in tp["html"]              # teaser, never the full article
    assert res.extra.get("teaser_email_post_id") == "email1"


def test_teaser_failure_does_not_fail_the_publish(monkeypatch):
    _mock_ghost(monkeypatch, teaser_fails=True)
    res = _provider().publish_post("x", PublishContent(text="Body", extra={"subtitle": "t"}))
    # Article is already live; a teaser-email failure must not un-publish it.
    assert res.url == "https://demo.ghost.io/brief/"
    assert "teaser_email_post_id" not in res.extra
