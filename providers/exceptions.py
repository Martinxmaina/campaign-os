"""Exception hierarchy for social platform providers."""


class ProviderError(Exception):
    """Base exception for all provider errors."""

    def __init__(
        self,
        message: str,
        platform: str = "",
        raw_response: dict | None = None,
    ):
        self.platform = platform
        self.raw_response = raw_response or {}
        super().__init__(message)


class OAuthError(ProviderError):
    """OAuth flow failure (invalid code, denied access, etc.)."""


class TokenExpiredError(ProviderError):
    """Access token has expired and refresh failed or is unavailable."""


class RateLimitError(ProviderError):
    """Platform rate limit exceeded."""

    def __init__(
        self,
        message: str,
        retry_after: int | None = None,
        **kwargs,
    ):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)


class PublishError(ProviderError):
    """Post publishing failed."""


class APIError(ProviderError):
    """Generic API error from the platform."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        **kwargs,
    ):
        self.status_code = status_code
        super().__init__(message, **kwargs)


class BlotatoStillPublishing(ProviderError):
    """Blotato accepted the post but it was still in-progress at our poll timeout.

    The engine parks the PlatformPost at ``publishing`` and persists the Blotato
    ``submission_id``; the reconcile beat task finalizes it later. We never
    re-submit (``POST /v2/posts`` is not idempotent → re-submit would duplicate).
    """

    def __init__(self, submission_id: str, **kwargs):
        self.submission_id = submission_id
        super().__init__(f"Blotato post {submission_id} still in progress", **kwargs)
