"""Tests for the X (Twitter) provider (X API v2)."""

import httpx
import pytest

from providers import get_provider
from providers.exceptions import APIError, RateLimitError
from providers.types import PostType, PublishContent


def test_twitter_registered():
    p = get_provider("twitter", {"client_id": "x", "client_secret": "y"})
    assert p.platform_name.lower() in ("x", "twitter")
    assert p.max_caption_length == 280


def test_twitter_publish_text(monkeypatch):
    p = get_provider("twitter", {"client_id": "x", "client_secret": "y"})

    def fake_post(self, url, **kwargs):
        return httpx.Response(201, json={"data": {"id": "1900000000000000000"}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = p.publish_post(
        access_token="t",
        content=PublishContent(text="hello world", post_type=PostType.TEXT),
    )
    assert result.platform_post_id == "1900000000000000000"


def test_twitter_publish_rate_limited(monkeypatch):
    p = get_provider("twitter", {"client_id": "x", "client_secret": "y"})

    def fake_post(self, url, **kwargs):
        return httpx.Response(429, headers={"Retry-After": "60"}, json={"title": "Too Many Requests"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(RateLimitError):
        p.publish_post(
            access_token="t",
            content=PublishContent(text="hello world", post_type=PostType.TEXT),
        )


def test_twitter_publish_api_error(monkeypatch):
    p = get_provider("twitter", {"client_id": "x", "client_secret": "y"})

    def fake_post(self, url, **kwargs):
        return httpx.Response(401, json={"title": "Unauthorized"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(APIError):
        p.publish_post(
            access_token="t",
            content=PublishContent(text="hello world", post_type=PostType.TEXT),
        )
