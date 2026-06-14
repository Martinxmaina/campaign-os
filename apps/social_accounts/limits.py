"""Per-platform content-limit enforcement.

The platform character limits were *defined* in
``SocialAccount.PLATFORM_CHAR_LIMITS`` and shown by the composer's client-side
counter, but never enforced on the server. An over-limit caption built by the
agent (Agent API) or pasted past the client counter would reach the provider,
where some adapters (Threads, YouTube) *silently truncated* it — publishing a
mangled post with no error.

This module is the single server-side guard. It is called:

* in ``apps.composer.services.create_post`` / ``update_post`` (compose-time),
* in the Agent API ``POST/PATCH /posts`` routers (→ 422), and
* in ``apps.publisher.engine._dispatch_to_provider`` immediately before the
  provider call (publish-time, against ``provider.max_caption_length``).

Keeping it tiny and dependency-free lets every layer reuse the same message.
"""

from __future__ import annotations


class CaptionTooLongError(ValueError):
    """Raised when a caption exceeds the platform's character limit.

    Subclasses ``ValueError`` so existing service-layer / API ``except
    ValueError`` handlers (which already map to 422) catch it without change.
    """


def validate_caption_length(text: str | None, *, limit: int, platform: str) -> None:
    """Raise ``CaptionTooLongError`` if ``text`` is longer than ``limit``.

    A ``None``/empty caption is always valid (no content to overflow). The
    message names the platform and both counts so the agent/operator can
    trim precisely.
    """
    length = len(text or "")
    if length > limit:
        raise CaptionTooLongError(
            f"Caption is {length} characters but {platform} allows at most "
            f"{limit}. Trim {length - limit} character(s)."
        )
