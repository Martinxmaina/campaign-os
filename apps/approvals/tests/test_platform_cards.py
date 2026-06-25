"""Tests for platform_cards.render_cards."""
import pytest
from apps.composer.models import Post, PlatformPost
from apps.approvals.platform_cards import render_cards


@pytest.mark.django_db
def test_render_cards_contains_platform_labels_and_caption(workspace, social_account):
    """render_cards returns one card per platform post with label and caption text."""
    li_account = social_account("linkedin", account_name="AfCEN LI", account_handle="@afcen")
    tw_account = social_account("twitter", account_name="AfCEN X", account_handle="@afcen_x")

    post = Post.objects.create(
        workspace=workspace,
        title="Test post",
        caption="Hello from AfCEN",
    )
    PlatformPost.objects.create(post=post, social_account=li_account)
    PlatformPost.objects.create(post=post, social_account=tw_account)

    html = render_cards(post)

    # Should have both platform labels
    assert "LinkedIn" in html
    assert "X" in html

    # Caption should appear (at least once per card, or in each)
    assert html.count("Hello from AfCEN") >= 2

    # Should be non-empty HTML
    assert "<div" in html


@pytest.mark.django_db
def test_render_cards_empty_when_no_platform_posts(workspace):
    """render_cards returns empty string when post has no platform posts."""
    post = Post.objects.create(workspace=workspace, title="Bare post", caption="no platforms")
    html = render_cards(post)
    assert html == ""


@pytest.mark.django_db
def test_render_cards_includes_account_handle(workspace, social_account):
    """render_cards shows the account handle or account name in each card."""
    account = social_account("instagram", account_name="AfCEN IG", account_handle="@afcen_ig")
    post = Post.objects.create(workspace=workspace, caption="IG caption")
    PlatformPost.objects.create(post=post, social_account=account)

    html = render_cards(post)
    # The handle is set and should appear directly
    assert "@afcen_ig" in html
    assert "Instagram" in html
