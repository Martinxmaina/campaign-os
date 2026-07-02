"""Dispatch-time resolution of the [NEXUS BRIEF LINK] token.

Campaign posts author social captions containing the literal token
``[NEXUS BRIEF LINK]`` where the Nexus Brief (Ghost) article link belongs.
The article URL does not exist until the sibling Ghost PlatformPost actually
publishes, so the token is resolved HERE — at dispatch, AFTER the
authoritative gate (exactly like ``apps.publisher.utm.apply_utm``) — against
the sibling's ``published_url``.

Three cases:
  * No token in the caption → caption returned unchanged (fast path).
  * Ghost sibling exists WITH a ``published_url`` → token replaced by it.
  * Ghost sibling exists WITHOUT a ``published_url`` yet → raise
    :class:`RetryableLinkError` so the engine parks the post on its normal
    retry loop until the article lands.
  * No Ghost sibling at all → token dropped (whitespace collapsed) with a
    warning; the caption still publishes rather than failing forever.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

NEXUS_TOKEN = "[NEXUS BRIEF LINK]"


class RetryableLinkError(Exception):
    """The sibling Ghost article exists but has not published yet.

    Non-terminal: the engine routes this to its exponential-backoff retry
    path (``_schedule_retry``) instead of marking the post FAILED.
    """


def resolve_nexus_link(platform_post, caption: str) -> str:
    """Replace ``NEXUS_TOKEN`` in ``caption`` with the sibling Ghost article URL.

    Pure function over the ORM graph: reads ``platform_post.post``'s children,
    never mutates anything. Raises :class:`RetryableLinkError` when the ghost
    sibling hasn't published yet (caller retries).
    """
    caption = caption or ""
    if NEXUS_TOKEN not in caption:
        return caption

    ghost_siblings = [
        pp
        for pp in platform_post.post.platform_posts.select_related("social_account").all()
        if pp.social_account.platform == "ghost"
    ]

    for sibling in ghost_siblings:
        if sibling.published_url:
            return caption.replace(NEXUS_TOKEN, sibling.published_url)

    if ghost_siblings:
        # Article is coming but hasn't landed — retry, don't fail.
        raise RetryableLinkError(
            f"Ghost sibling {ghost_siblings[0].id} has no published_url yet"
        )

    # No Ghost channel on this post at all: drop the token rather than
    # publishing the literal placeholder. ponytail: collapse only horizontal
    # runs so authored line breaks survive.
    logger.warning(
        "No Ghost sibling for post %s — dropping %s token from caption",
        platform_post.post_id,
        NEXUS_TOKEN,
    )
    stripped = caption.replace(NEXUS_TOKEN, "")
    return re.sub(r"[ \t]{2,}", " ", stripped).strip()
