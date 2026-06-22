"""Publish / schedule a HERALD console draft through the real gate.

The console Drafts surface (``/console/drafts/<content_id>``) shows agent-service
content items read-only. This module makes them actionable: materialise a Post
(``ensure_post_from_content_item``), run the caption through the **authoritative
gate** (``apps.publisher.gate_client.check_gate`` — the same path the composer,
decks and outreach use), and only on a passing verdict stamp gate_id +
content_hash onto the PlatformPosts and schedule them. "Publish now" then runs
one synchronous publish cycle so the result (or a gate block) is immediate.

No bypass: a flag/block verdict returns the findings and never schedules, so the
publish chokepoint stays authoritative.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.approvals.intake_publish import ensure_post_from_content_item
from apps.composer.models import PlatformPost
from apps.publisher.gate_client import GateError, check_gate
from apps.publisher.gate_hash import canonical_content_hash

logger = logging.getLogger(__name__)

# Gate verdicts that clear a post for scheduling. "flag" is advisory but still
# blocks auto-publish here — only a clean pass goes out from the Drafts surface.
_PASS_VERDICTS = {"pass", "approved"}


def publish_content_item(content: dict, workspace, author, *, scheduled_at=None) -> dict:
    """Publish (or schedule) a HERALD draft through the gate.

    Returns a result dict:
      * ``{"ok": True, "post_id", "scheduled", "published", "accounts"}`` on success
      * ``{"ok": False, "reason": "no_accounts"|"empty"|"gate_error"}``
      * ``{"ok": False, "reason": "gate_blocked", "verdict", "findings"}`` when the
        gate refuses the content (findings are surfaced to the user; nothing ships)

    ``scheduled_at=None`` means publish now (a synchronous cycle runs); a future
    datetime schedules it for the beat cycle to publish.
    """
    post = ensure_post_from_content_item(content, workspace, author)

    caption = (post.caption or "").strip()
    if not caption:
        return {"ok": False, "reason": "empty", "post_id": str(post.id)}

    platform_posts = list(post.platform_posts.all())
    if not platform_posts:
        return {"ok": False, "reason": "no_accounts", "post_id": str(post.id)}

    # Authoritative gate — fail closed on any transport/config error.
    try:
        result = check_gate(caption, track=post.track or None, content_type="post")
    except GateError:
        logger.warning("draft publish gate error", exc_info=True)
        return {"ok": False, "reason": "gate_error", "post_id": str(post.id)}

    verdict = str(result.get("verdict") or "").lower()
    if verdict not in _PASS_VERDICTS:
        return {
            "ok": False,
            "reason": "gate_blocked",
            "verdict": verdict or "block",
            "findings": result.get("findings") or [],
            "post_id": str(post.id),
        }

    gate_id = result.get("gate_id")
    now = timezone.now()
    when = scheduled_at or now
    content_hash = canonical_content_hash(caption)
    for pp in platform_posts:
        pp.gate_id = gate_id
        pp.content_hash = content_hash
        pp.scheduled_at = when
        pp.status = PlatformPost.Status.SCHEDULED
        pp.save(update_fields=["gate_id", "content_hash", "scheduled_at", "status", "updated_at"])

    publishing_now = scheduled_at is None or scheduled_at <= now
    published = 0
    if publishing_now:
        # Run the real publish cycle synchronously so the gate re-verifies and
        # the user sees the outcome immediately (the cycle is the chokepoint).
        from apps.publisher.engine import PublishEngine

        try:
            published = PublishEngine().poll_and_publish() or 0
        except Exception:
            logger.warning("draft synchronous publish failed", exc_info=True)

    post.refresh_from_db()
    return {
        "ok": True,
        "post_id": str(post.id),
        "scheduled": not publishing_now,
        "published": bool(published) or post.status == "published",
        "accounts": len(platform_posts),
    }
