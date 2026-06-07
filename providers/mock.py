"""Mock social provider — deterministic, network-free publishing.

Used by the test suite and the end-to-end slice acceptance flow so a
publish can be exercised without live OAuth or real platform APIs. It is
registered into ``PROVIDER_REGISTRY`` only when
``settings.ENABLE_MOCK_PROVIDER`` is truthy (default False), so it can
never reach a real deployment by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .base import SocialProvider
from .types import (
    AccountProfile,
    AuthType,
    MediaType,
    PostType,
    PublishContent,
    PublishResult,
)


@dataclass(frozen=True)
class MockPublishResult:
    """Lightweight publish result for the mock ``publish()`` convenience path.

    Mirrors the slice-acceptance contract (``success`` + ``status_code``)
    while the canonical ``publish_post()`` path returns the project's real
    :class:`~providers.types.PublishResult`.
    """

    platform_post_id: str
    success: bool = True
    status_code: int = 201
    url: str | None = None


def _synthetic_post_id() -> str:
    return f"mock_{uuid4().hex[:16]}"


class MockProvider(SocialProvider):
    """A no-op provider that returns synthetic ids instead of calling out."""

    @property
    def platform_name(self) -> str:
        return "Mock"

    @property
    def auth_type(self) -> AuthType:
        return AuthType.OAUTH2

    @property
    def max_caption_length(self) -> int:
        return 10000

    @property
    def supported_post_types(self) -> list[PostType]:
        return [PostType.TEXT, PostType.IMAGE, PostType.VIDEO]

    @property
    def supported_media_types(self) -> list[MediaType]:
        return [MediaType.JPEG, MediaType.PNG, MediaType.MP4]

    @property
    def required_scopes(self) -> list[str]:
        return []

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def get_profile(self, access_token: str) -> AccountProfile:
        return AccountProfile(
            platform_id="mock_account",
            name="Mock Account",
            handle="mock",
        )

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        """Canonical publish path — returns the project's PublishResult."""
        post_id = _synthetic_post_id()
        return PublishResult(
            platform_post_id=post_id,
            url=f"https://mock.local/p/{post_id}",
            extra={"success": True, "status_code": 201},
        )

    def publish(self, tokens: dict | None = None, content: PublishContent | None = None) -> MockPublishResult:
        """Slice-acceptance convenience wrapper.

        Returns a result exposing ``success`` / ``status_code`` directly,
        matching the acceptance contract. The id is generated the same way
        as :meth:`publish_post`.
        """
        post_id = _synthetic_post_id()
        return MockPublishResult(
            platform_post_id=post_id,
            success=True,
            status_code=201,
            url=f"https://mock.local/p/{post_id}",
        )
