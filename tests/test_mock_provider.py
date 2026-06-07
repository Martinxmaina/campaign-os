"""Mock provider — registered only behind ENABLE_MOCK_PROVIDER.

The mock provider gives the test suite and the slice acceptance flow a
deterministic, network-free publish path that returns a synthetic
platform post id. It is absent from the registry by default and only
appears when ``settings.ENABLE_MOCK_PROVIDER`` is truthy.
"""

from __future__ import annotations

import pytest

import providers
from providers import get_provider
from providers.types import PostType, PublishContent


def test_mock_publish_returns_synthetic_id(settings):
    settings.ENABLE_MOCK_PROVIDER = True
    providers._register_mock()  # idempotent registration hook
    p = get_provider("mock", {})
    r = p.publish(
        tokens={},
        content=PublishContent(text="hi", post_type=PostType.TEXT),
    )
    assert r.success and r.platform_post_id.startswith("mock_")


def test_mock_publish_post_returns_synthetic_id(settings):
    """The real SocialProvider publish_post() path also yields a mock_ id."""
    settings.ENABLE_MOCK_PROVIDER = True
    providers._register_mock()
    p = get_provider("mock", {})
    r = p.publish_post(
        access_token="",
        content=PublishContent(text="hi", post_type=PostType.TEXT),
    )
    assert r.platform_post_id.startswith("mock_")


def test_mock_absent_by_default(settings):
    settings.ENABLE_MOCK_PROVIDER = False
    with pytest.raises(ValueError):
        get_provider("mock", {})
