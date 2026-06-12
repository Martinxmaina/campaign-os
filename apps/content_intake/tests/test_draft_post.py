from unittest.mock import patch
import pytest
from apps.content_intake.models import ContentIntake
from apps.content_intake.draft_post import ensure_draft_post
from apps.composer.models import Post


def _item(workspace, **kw):
    d = dict(workspace=workspace, external_id="DP-1", angle="Solar growth",
             proof_point="IEA", sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
             status=ContentIntake.Status.DRAFTING, herald_content_id="ci-1")
    d.update(kw)
    return ContentIntake.objects.create(**d)


@pytest.mark.django_db
def test_creates_post_from_content_item(workspace):
    item = _item(workspace)
    content = {"id": "ci-1", "body": "AI-written body about solar.", "title": "Solar"}
    with patch("apps.content_intake.draft_post.safe_get", return_value=content):
        post = ensure_draft_post(item)
    assert isinstance(post, Post)
    assert "AI-written body" in post.caption
    item.refresh_from_db()
    assert item.post_id == post.pk


@pytest.mark.django_db
def test_reuses_existing_post(workspace):
    item = _item(workspace)
    with patch("apps.content_intake.draft_post.safe_get", return_value={"id": "ci-1", "body": "b", "title": "t"}):
        p1 = ensure_draft_post(item)
        p2 = ensure_draft_post(item)
    assert p1.pk == p2.pk


@pytest.mark.django_db
def test_minimal_fallback_when_content_not_ready(workspace):
    item = _item(workspace, herald_content_id="")
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        post = ensure_draft_post(item)
    assert isinstance(post, Post)
    # Falls back to the intake's own angle/proof so the composer has content
    assert "Solar growth" in (post.title + post.caption)
    item.refresh_from_db()
    assert item.post_id == post.pk


@pytest.mark.django_db
def test_ensure_draft_post_assigns_reviewer_and_pending(workspace):
    from unittest.mock import patch
    from django.contrib.auth import get_user_model
    from apps.members.models import WorkspaceMembership
    from apps.content_intake.models import ContentIntake
    from apps.content_intake.draft_post import ensure_draft_post
    dennis = get_user_model().objects.create_user(email="dennis@afcen.org", password="pw12345678", name="Dennis")
    WorkspaceMembership.objects.create(user=dennis, workspace=workspace, workspace_role="member")
    item = ContentIntake.objects.create(workspace=workspace, external_id="DR-1",
        pillar_theme="Energy", angle="Solar", sensitivity="public_safe", status="drafting")
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        post = ensure_draft_post(item)
    assert post.review_assignee == dennis
    assert post.review_state == "pending"


@pytest.mark.django_db
def test_ensure_draft_post_does_not_downgrade_approved(workspace):
    from unittest.mock import patch
    from apps.content_intake.models import ContentIntake
    from apps.content_intake.draft_post import ensure_draft_post
    from apps.composer.models import Post
    post = Post.objects.create(workspace=workspace, title="t", caption="c", review_state="approved")
    item = ContentIntake.objects.create(workspace=workspace, external_id="DR-2", angle="x",
        sensitivity="public_safe", status="drafting", post=post)
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        out = ensure_draft_post(item)
    assert out.pk == post.pk
    out.refresh_from_db()
    assert out.review_state == "approved"  # not downgraded
