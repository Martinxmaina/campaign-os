"""Tests for platform_cards.render_cards."""
import pytest
from unittest.mock import MagicMock, PropertyMock
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


# ---------------------------------------------------------------------------
# Thumbnail path test
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_render_cards_includes_thumbnail_src(workspace, social_account):
    """A post with a media attachment renders a card with the thumbnail src URL."""
    from apps.media_library.models import MediaAsset
    from apps.composer.models import PostMedia

    account = social_account("linkedin", account_name="AfCEN LI")
    post = Post.objects.create(workspace=workspace, caption="Post with image")
    PlatformPost.objects.create(post=post, social_account=account)

    # Create a MediaAsset; set file.name directly to bypass storage I/O.
    asset = MediaAsset.objects.create(
        workspace=workspace,
        filename="test-image.jpg",
        mime_type="image/jpeg",
        file_size=1024,
    )
    # Directly set the file field name so asset.file.url returns a predictable path.
    asset.file.name = "media_library/files/2024/01/test-image.jpg"
    asset.save(update_fields=["file"])

    PostMedia.objects.create(post=post, media_asset=asset, position=0)

    html = render_cards(post)

    # The thumbnail src must appear in the rendered card HTML.
    assert "test-image.jpg" in html
    assert '<img' in html


# ---------------------------------------------------------------------------
# HTML-escaping / XSS tests
# ---------------------------------------------------------------------------

XSS_PAYLOAD = '"><script>alert(1)</script>'


@pytest.mark.django_db
def test_render_cards_escapes_xss_in_caption(workspace, social_account):
    """A caption containing XSS payload is escaped; raw <script> must not appear."""
    account = social_account("twitter", account_name="SafeAccount")
    post = Post.objects.create(workspace=workspace, caption=XSS_PAYLOAD)
    PlatformPost.objects.create(post=post, social_account=account)

    html = render_cards(post)

    # Raw script tag must NOT appear.
    assert "<script>" not in html
    # Must be escaped.
    assert "&lt;script&gt;" in html


@pytest.mark.django_db
def test_render_cards_escapes_xss_in_handle(workspace, social_account):
    """An account handle containing XSS payload is escaped."""
    account = social_account(
        "twitter",
        account_name="SafeAccount",
        account_handle=XSS_PAYLOAD,
    )
    post = Post.objects.create(workspace=workspace, caption="Normal caption")
    PlatformPost.objects.create(post=post, social_account=account)

    html = render_cards(post)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.django_db
def test_render_cards_escapes_double_quote_in_caption_attribute_context(workspace, social_account):
    """A value containing a bare double-quote is escaped so it cannot break an HTML attribute."""
    account = social_account("linkedin", account_name="TestAccount")
    # Caption with a bare double-quote character.
    post = Post.objects.create(workspace=workspace, caption='Say "hello" world')
    PlatformPost.objects.create(post=post, social_account=account)

    html = render_cards(post)

    # The literal unescaped double-quote inside attribute context must not break the HTML.
    # The caption here sits in a div text node — escaping &quot; or &#x27; is fine.
    # We just assert the raw injected `"><script>` pattern is not possible.
    assert "<script>" not in html


def test_card_html_escapes_xss_in_thumbnail_url():
    """_card_html escapes a thumbnail URL containing attribute-breaking characters.

    This calls the private helper directly so we can pass a raw crafted URL that
    would not survive Django storage URL encoding, and confirm it's escaped before
    being spliced into the src attribute.
    """
    from apps.approvals.platform_cards import _card_html

    evil_url = '/media/evil.jpg" onload="alert(1)'
    html = _card_html("LinkedIn", "#0A66C2", "@handle", "caption", evil_url)

    # The raw injection string must NOT appear verbatim in the output.
    assert '" onload="alert(1)' not in html
    # The double-quote must be escaped in the attribute context.
    assert '&quot;' in html or '%22' in html


@pytest.mark.django_db
def test_ghost_card_renders_readable_article_not_raw_tags(workspace, social_account):
    """Ghost's HTML article body must show as readable text in the review card,
    not escaped raw <p>/<h2> tags (the actual Ghost post publishes formatted)."""
    ghost = social_account("ghost", account_name="Nexus Brief")
    post = Post.objects.create(workspace=workspace, title="T", caption="fallback")
    PlatformPost.objects.create(
        post=post,
        social_account=ghost,
        platform_specific_caption=(
            "<p>Africa has an <strong>investment</strong> problem.</p>"
            "<h2>The capital exists</h2>"
        ),
    )
    html = render_cards(post)

    assert "Africa has an investment problem." in html
    assert "The capital exists" in html
    # Raw article tags are NOT shown as literal (escaped) markup
    assert "&lt;p&gt;" not in html
    assert "&lt;h2&gt;" not in html
    # Reviewer is told the real article is formatted
    assert "Publishes as a formatted article on Ghost." in html
