from unittest.mock import MagicMock

import pytest

from providers import get_provider
from providers.blotato import BlotatoFacebookProvider, BlotatoInstagramProvider, BlotatoTwitterProvider
from providers.exceptions import BlotatoStillPublishing, PublishError
from providers.types import PublishContent


def _resp(json_data, text="", status=200):
    r = MagicMock()
    r.json.return_value = json_data
    r.text = text
    r.status_code = status
    return r


def _content(text="hi", extra=None, media_urls=None):
    return PublishContent(text=text, media_urls=media_urls or [], extra=extra or {})


def _fake_clock():
    # monotonic() returns increasing values that jump past the timeout quickly.
    state = {"t": 0}

    def clock():
        state["t"] += 100
        return state["t"]

    return clock


def test_registry_exposes_blotato_targets():
    assert isinstance(get_provider("blotato_instagram", {"api_key": "k"}), BlotatoInstagramProvider)
    assert get_provider("blotato_instagram", {"api_key": "k"}).target_type == "instagram"
    assert get_provider("blotato_facebook", {"api_key": "k"}).target_type == "facebook"


def test_registry_exposes_blotato_twitter():
    provider = get_provider("blotato_twitter", {"api_key": "k"})
    assert isinstance(provider, BlotatoTwitterProvider)
    assert provider.target_type == "twitter"
    assert provider.max_caption_length == 280
    assert provider.platform_name == "X / Twitter (Blotato)"


def test_publish_submits_then_returns_published(monkeypatch):
    p = BlotatoInstagramProvider({"api_key": "k"})
    calls = []

    def fake_request(method, url, **kw):
        calls.append((method, url, kw))
        if url.endswith("/posts"):
            body = kw["json"]["post"]
            assert body["accountId"] == "98432"
            assert body["content"]["platform"] == "instagram"
            assert body["target"]["targetType"] == "instagram"
            assert body["content"]["mediaUrls"] == ["https://img/x.jpg"]
            return _resp({"postSubmissionId": "sub1"})
        return _resp({"status": "published", "publicUrl": "https://ig/p/1"})

    monkeypatch.setattr(p, "_request", fake_request)
    res = p.publish_post("98432", _content(extra={"blotato_account_id": "98432"},
                                          media_urls=["https://img/x.jpg"]))
    assert res.platform_post_id == "sub1"
    assert res.url == "https://ig/p/1"
    assert any(u.endswith("/posts/sub1") for _, u, _ in calls)  # polled


def test_publish_failed_raises_publish_error(monkeypatch):
    p = BlotatoInstagramProvider({"api_key": "k"})

    def fake_request(method, url, **kw):
        if url.endswith("/posts"):
            return _resp({"postSubmissionId": "sub2"})
        return _resp({"status": "failed", "errorMessage": "caption too long"})

    monkeypatch.setattr(p, "_request", fake_request)
    with pytest.raises(PublishError, match="caption too long"):
        p.publish_post("98432", _content(extra={"blotato_account_id": "98432"}))


def test_publish_timeout_raises_still_publishing(monkeypatch):
    monkeypatch.setattr("providers.blotato.time.sleep", lambda *_: None)
    monkeypatch.setattr("providers.blotato.time.monotonic", _fake_clock())
    p = BlotatoInstagramProvider({"api_key": "k"})

    def fake_request(method, url, **kw):
        if url.endswith("/posts"):
            return _resp({"postSubmissionId": "sub3"})
        return _resp({"status": "in-progress"})

    monkeypatch.setattr(p, "_request", fake_request)
    with pytest.raises(BlotatoStillPublishing) as ei:
        p.publish_post("98432", _content(extra={"blotato_account_id": "98432"}))
    assert ei.value.submission_id == "sub3"


def test_facebook_target_includes_page_id(monkeypatch):
    p = BlotatoFacebookProvider({"api_key": "k"})
    captured = {}

    def fake_request(method, url, **kw):
        if url.endswith("/posts"):
            captured["target"] = kw["json"]["post"]["target"]
            return _resp({"postSubmissionId": "s"})
        return _resp({"status": "published", "publicUrl": "u"})

    monkeypatch.setattr(p, "_request", fake_request)
    p.publish_post("1", _content(extra={"blotato_account_id": "1", "page_id": "PAGE9"}))
    assert captured["target"] == {"targetType": "facebook", "pageId": "PAGE9"}


def test_missing_account_id_fails_closed():
    p = BlotatoInstagramProvider({"api_key": "k"})
    with pytest.raises(PublishError, match="account"):
        p.publish_post("", _content(extra={}))
