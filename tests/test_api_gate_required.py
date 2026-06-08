"""The REST create/schedule path must require a ``gate_id`` before a post
can be queued for publishing, and must persist ``gate_id`` +
``content_hash`` on the created ``PlatformPost`` — defence-in-depth atop
the publish-engine gate hook (Task 9).

The plan's pseudocode targets a ``platform_posts`` array; the real fork
API is single-account (``social_account_id`` + ``caption`` on the body),
so these tests adapt to that surface while asserting the same contract.
"""

from __future__ import annotations

import pytest

from tests.api_helpers import api_post, make_api_key


@pytest.mark.django_db
def test_schedule_without_gate_id_rejected():
    issued = make_api_key()
    resp = api_post(
        "/api/v1/posts/",
        issued,
        {
            "action": "schedule",
            "scheduled_at": "2030-01-01T00:00:00Z",
            "title": "t",
            "caption": "hi",
            "social_account_id": str(issued.social_account.id),
        },
    )
    assert resp.status_code == 422, resp.content
    assert "gate_id" in resp.json()["detail"].lower()


@pytest.mark.django_db
def test_schedule_with_gate_id_persists_fields():
    issued = make_api_key()
    gate_id = "33333333-3333-3333-3333-333333333333"
    resp = api_post(
        "/api/v1/posts/",
        issued,
        {
            "action": "schedule",
            "scheduled_at": "2030-01-01T00:00:00Z",
            "gate_id": gate_id,
            "title": "t",
            "caption": "hi",
            "social_account_id": str(issued.social_account.id),
        },
    )
    assert resp.status_code in (200, 201), resp.content

    from apps.composer.models import PlatformPost
    from apps.publisher.gate_hash import canonical_content_hash

    pp = PlatformPost.objects.get(post_id=resp.json()["id"])
    assert str(pp.gate_id) == gate_id
    assert pp.content_hash == canonical_content_hash("hi", [])


@pytest.mark.django_db
def test_draft_may_omit_gate_id():
    """Drafts are not publishable, so gate_id is optional for them."""
    issued = make_api_key()
    resp = api_post(
        "/api/v1/posts/",
        issued,
        {
            "action": "draft",
            "caption": "draft body",
            "social_account_id": str(issued.social_account.id),
        },
    )
    assert resp.status_code in (200, 201), resp.content
