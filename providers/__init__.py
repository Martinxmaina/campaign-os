"""Social platform provider registry.

Maps PlatformCredential.Platform enum values to provider classes.
Use get_provider() to instantiate a provider with app credentials.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .facebook import FacebookProvider
from .ghost import GhostProvider
from .instagram import InstagramProvider
from .instagram_login import InstagramLoginProvider
from .linkedin_company import LinkedInCompanyProvider
from .linkedin_personal import LinkedInPersonalProvider
from .threads import ThreadsProvider
from .twitter import TwitterProvider
from .youtube import YouTubeProvider

if TYPE_CHECKING:
    from .base import SocialProvider

PROVIDER_REGISTRY: dict[str, type[SocialProvider]] = {
    "facebook": FacebookProvider,
    "instagram": InstagramProvider,
    "instagram_login": InstagramLoginProvider,
    "linkedin_personal": LinkedInPersonalProvider,
    "linkedin_company": LinkedInCompanyProvider,
    "youtube": YouTubeProvider,
    "threads": ThreadsProvider,
    "twitter": TwitterProvider,
    "ghost": GhostProvider,
}


def _register_mock() -> None:
    """Sync the mock provider into the registry to match the current setting.

    Idempotent: adds ``"mock"`` when ``settings.ENABLE_MOCK_PROVIDER`` is
    truthy and removes it otherwise, so the registry never carries the mock
    provider in a deployment where the flag is off. Safe to call repeatedly.
    """
    from django.conf import settings

    if getattr(settings, "ENABLE_MOCK_PROVIDER", False):
        from .mock import MockProvider

        PROVIDER_REGISTRY["mock"] = MockProvider
    else:
        PROVIDER_REGISTRY.pop("mock", None)


def get_provider(platform: str, credentials: dict | None = None) -> SocialProvider:
    """Instantiate and return a provider for the given platform.

    Args:
        platform: A PlatformCredential.Platform value (e.g. "facebook").
        credentials: Platform app credentials (client_id, client_secret, etc.)
                     from PlatformCredential or settings.PLATFORM_CREDENTIALS_FROM_ENV.
                     If None, falls back to env credentials from
                     ``settings.PLATFORM_CREDENTIALS_FROM_ENV``.

    Raises:
        ValueError: If no provider is registered for the given platform.
    """
    # Keep the mock entry in sync with the current setting so toggling
    # ENABLE_MOCK_PROVIDER at runtime (e.g. in tests) is always honoured.
    _register_mock()
    provider_cls = PROVIDER_REGISTRY.get(platform)
    if provider_cls is None:
        raise ValueError(f"No provider registered for platform: {platform}")
    if credentials is None:
        from django.conf import settings

        env_creds = getattr(settings, "PLATFORM_CREDENTIALS_FROM_ENV", {})
        credentials = env_creds.get(platform, {})
    return provider_cls(credentials=credentials)


# Register the mock provider at import time when the flag is on. Wrapped so a
# missing/unconfigured Django settings module never breaks the import.
try:  # pragma: no cover - import-time best effort
    _register_mock()
except Exception:  # noqa: BLE001
    pass
