# apps/approvals/tests/test_approve_view_creates_post.py
"""View-level (controller) tests for approval_decide → Post creation.

These exercise the full _try_create_post path that unit tests of
create_post_from_content miss: the target_ref field name, the absence of any
GET /approvals/{id} round-trip, decide-success ordering, and idempotency.
"""
from unittest.mock import patch

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals import console_views
from apps.composer.models import Post
from apps.content_intake.models import ContentIntake


@pytest.fixture
def op(db):
    return User.objects.create_user(
        email="opview@x.io", password="pw", name="OpView", tos_accepted_at=timezone.now()
    )


def _post_request(workspace, op, data):
    rf = RequestFactory()
    request = rf.post("/console/approvals/a1/decide", data)
    request.user = op
    request.workspace = workspace
    return request


@pytest.mark.django_db
def test_approve_creates_post_via_view(workspace, op, monkeypatch):
    intake = ContentIntake.objects.create(
        workspace=workspace, external_id="P-V1", angle="Solar story",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING, herald_content_id="c1",
        channel_targets=[{"platform": "linkedin"}],
    )
    calls = {"safe_get_paths": []}

    def fake_agent_post(path, json=None):
        calls["decide"] = path
        return {"status": "approved"}

    def fake_safe_get(path, default=None):
        calls["safe_get_paths"].append(path)
        # Only /content/items/{id} is fetched — there is NO GET /approvals/{id}.
        if path == "/content/items/c1":
            return {"id": "c1", "body": "Solar is booming.", "title": "Solar"}
        return default

    monkeypatch.setattr(console_views, "agent_post", fake_agent_post)
    monkeypatch.setattr(console_views, "safe_get", fake_safe_get)

    request = _post_request(workspace, op, {"decision": "approve", "target_ref": "c1"})
    resp = console_views.approval_decide(request, "a1")

    assert resp.status_code in (302, 303)
    assert calls["decide"] == "/approvals/a1/decide"
    # The non-existent GET /approvals/{id} route must never be called.
    assert "/approvals/a1" not in calls["safe_get_paths"]
    assert calls["safe_get_paths"] == ["/content/items/c1"]

    intake.refresh_from_db()
    assert intake.post_id is not None
    assert Post.objects.filter(workspace=workspace).count() == 1
    assert "Solar is booming" in intake.post.caption


@pytest.mark.django_db
def test_approve_does_not_create_post_when_decide_fails(workspace, op, monkeypatch):
    """If the agent-service decide call fails, no local Post is created
    (the two systems must not diverge)."""
    ContentIntake.objects.create(
        workspace=workspace, external_id="P-V2", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING, herald_content_id="c1",
        channel_targets=[{"platform": "linkedin"}],
    )

    def boom(path, json=None):
        raise RuntimeError("agent-service down")

    safe_get_called = {"n": 0}

    def fake_safe_get(path, default=None):
        safe_get_called["n"] += 1
        return default

    monkeypatch.setattr(console_views, "agent_post", boom)
    monkeypatch.setattr(console_views, "safe_get", fake_safe_get)

    request = _post_request(workspace, op, {"decision": "approve", "target_ref": "c1"})
    resp = console_views.approval_decide(request, "a1")

    assert resp.status_code in (302, 303)
    assert Post.objects.filter(workspace=workspace).count() == 0
    # _try_create_post must not run at all when decide failed.
    assert safe_get_called["n"] == 0


@pytest.mark.django_db
def test_approve_is_idempotent_no_orphan_posts(workspace, op, monkeypatch):
    """Re-approving the same intake must not create a second Post and orphan
    the first."""
    intake = ContentIntake.objects.create(
        workspace=workspace, external_id="P-V3", angle="Solar",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING, herald_content_id="c1",
        channel_targets=[{"platform": "linkedin"}],
    )

    monkeypatch.setattr(console_views, "agent_post",
                        lambda path, json=None: {"status": "approved"})
    monkeypatch.setattr(console_views, "safe_get",
                        lambda path, default=None: (
                            {"id": "c1", "body": "Body", "title": "T"}
                            if path == "/content/items/c1" else default))

    data = {"decision": "approve", "target_ref": "c1"}
    console_views.approval_decide(_post_request(workspace, op, data), "a1")
    intake.refresh_from_db()
    first_post_id = intake.post_id
    assert first_post_id is not None

    # Second approval fires again.
    console_views.approval_decide(_post_request(workspace, op, data), "a1")
    intake.refresh_from_db()

    assert intake.post_id == first_post_id
    assert Post.objects.filter(workspace=workspace).count() == 1
