"""Regression tests for the email-routing + Blotato-key fixes."""
import pytest


def test_blotato_headers_fall_back_to_settings_api_key(settings):
    """BlotatoProvider resolves the api key from BLOTATO_API_KEY when the
    per-platform credential dict is empty (fixes health-check ERRORs)."""
    settings.BLOTATO_API_KEY = "re_envkey_xyz"
    from providers import get_provider

    p = get_provider("blotato_instagram", {})  # empty credentials
    assert p._headers()["blotato-api-key"] == "re_envkey_xyz"


@pytest.mark.django_db
def test_publisher_email_prefers_workspace_copy_email(workspace):
    """Publish notifications go to the workspace publish inbox (review.copy_email),
    not the assigner's personal account email."""
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.approvals import review_views
    from apps.approvals.models import ReviewAssignment
    from apps.composer.models import Post

    assigner = User.objects.create_user(
        email="personal@gmail.com", password="x", name="Someone",
        tos_accepted_at=timezone.now())
    post = Post.objects.create(workspace=workspace, title="P", caption="c")
    a = ReviewAssignment.objects.create(
        post=post, assigned_by=assigner, reviewer_email="r@x.co")

    # review.copy_email default is martin.maina@africacen.org → wins over the gmail assigner
    assert review_views._publisher_email(a) == "martin.maina@africacen.org"
