# apps/approvals/tests/test_approve_creates_post.py
from unittest.mock import patch
import pytest
from apps.content_intake.models import ContentIntake
from apps.composer.models import Post
from apps.approvals.intake_publish import create_post_from_content


@pytest.mark.django_db
def test_create_post_from_content_builds_post(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace, external_id="P-1", angle="Solar story",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING,
        herald_content_id="ci-9",
        channel_targets=[{"platform": "linkedin", "account": "waiis"}],
    )
    content = {"id": "ci-9", "body": "Solar is booming across East Africa.", "title": "Solar"}
    post = create_post_from_content(content, intake)
    assert isinstance(post, Post)
    assert post.workspace_id == workspace.pk
    assert "Solar is booming" in post.caption
    intake.refresh_from_db()
    assert intake.post_id == post.pk


@pytest.mark.django_db
def test_create_post_no_matching_account_leaves_draft(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace, external_id="P-2", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING, herald_content_id="ci-10",
        channel_targets=[{"platform": "linkedin"}],
    )
    content = {"id": "ci-10", "body": "Body text", "title": "T"}
    post = create_post_from_content(content, intake)
    # No SocialAccount exists, so no PlatformPost — post stays draft-only
    assert post.platform_posts.count() == 0
