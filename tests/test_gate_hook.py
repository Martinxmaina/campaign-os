import pytest
from unittest.mock import patch

from apps.composer.models import PlatformPost
from apps.publisher.engine import Publisher
from apps.publisher.gate_hash import canonical_content_hash

# Helpers build a due PlatformPost via the due_platform_post_factory fixture
# (see conftest.py).


@pytest.mark.django_db
def test_publish_blocked_without_gate_id(due_platform_post_factory):
    pp = due_platform_post_factory(gate_id=None, content_hash="")
    with patch("apps.publisher.engine.get_provider") as gp:
        Publisher().poll_and_publish()
        gp.assert_not_called()
    pp.refresh_from_db()
    assert pp.status != PlatformPost.Status.PUBLISHED


@pytest.mark.django_db
def test_publish_blocked_on_hash_mismatch(due_platform_post_factory):
    pp = due_platform_post_factory(
        gate_id="11111111-1111-1111-1111-111111111111",
        content_hash=canonical_content_hash("real text"),
    )
    with patch(
        "apps.publisher.engine.verify_gate",
        return_value={"verdict": "pass", "content_hash": "DIFFERENT"},
    ), patch("apps.publisher.engine.get_provider") as gp:
        Publisher().poll_and_publish()
        gp.assert_not_called()
    pp.refresh_from_db()
    assert pp.status != PlatformPost.Status.PUBLISHED


@pytest.mark.django_db
def test_publish_allowed_when_pass_and_hash_match(due_platform_post_factory, settings):
    settings.ENABLE_MOCK_PROVIDER = True
    h = canonical_content_hash("real text")
    pp = due_platform_post_factory(
        gate_id="22222222-2222-2222-2222-222222222222",
        content_hash=h,
        platform="mock",
    )
    with patch(
        "apps.publisher.engine.verify_gate",
        return_value={"verdict": "pass", "content_hash": h},
    ):
        Publisher().poll_and_publish()
    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.PUBLISHED
    assert pp.platform_post_id.startswith("mock_")
