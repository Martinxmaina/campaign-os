"""FIX C regression: editing gated content clears the gate.

PATCH-ing the caption of a scheduled, gated post must set gate_id=None and
content_hash="" on every gated child, forcing re-approval. A subsequent
publish attempt is then blocked by the engine's authoritative chokepoint
(missing gate_id → GATE BLOCK, not PUBLISHED).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.api_helpers import api_patch, api_post, make_api_key


@pytest.mark.django_db
def test_patch_caption_clears_gate_and_blocks_publish():
    issued = make_api_key()
    gate_id = "44444444-4444-4444-4444-444444444444"

    # Create a scheduled, gated post.
    resp = api_post(
        "/api/v1/posts/",
        issued,
        {
            "action": "schedule",
            "scheduled_at": "2030-01-01T00:00:00Z",
            "gate_id": gate_id,
            "title": "t",
            "caption": "approved text",
            "social_account_id": str(issued.social_account.id),
        },
    )
    assert resp.status_code in (200, 201), resp.content
    post_id = resp.json()["id"]

    from apps.composer.models import PlatformPost
    from apps.publisher.engine import Publisher

    pp = PlatformPost.objects.get(post_id=post_id)
    assert str(pp.gate_id) == gate_id
    assert pp.content_hash != ""

    # Edit the caption — this must clear the gate.
    patch_resp = api_patch(
        f"/api/v1/posts/{post_id}",
        issued,
        {"caption": "EDITED text — not what the approver saw"},
    )
    assert patch_resp.status_code == 200, patch_resp.content

    pp.refresh_from_db()
    assert pp.gate_id is None
    assert pp.content_hash == ""

    # Make the post due so the poll loop would attempt to publish it.
    from datetime import timedelta

    from django.utils import timezone

    pp.scheduled_at = timezone.now() - timedelta(minutes=5)
    pp.save(update_fields=["scheduled_at"])

    # A subsequent publish must be blocked (no gate_id → GATE BLOCK).
    with patch("apps.publisher.engine.get_provider") as gp:
        Publisher().poll_and_publish()
        gp.assert_not_called()

    pp.refresh_from_db()
    assert pp.status == PlatformPost.Status.FAILED
    assert pp.status != PlatformPost.Status.PUBLISHED
    assert "GATE BLOCK" in pp.publish_error
