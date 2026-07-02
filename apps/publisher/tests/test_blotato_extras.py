# apps/publisher/tests/test_blotato_extras.py
import pytest


def _make(db_platform, provider_config):
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="AfCEN")
    ws = Workspace.objects.create(organization=org, name="WAIIS")
    return SocialAccount.objects.create(
        workspace=ws, platform=db_platform, account_platform_id="98432",
        account_name="AfCEN", provider_config=provider_config)


@pytest.mark.django_db
def test_blotato_extras_injects_account_id_and_page_id():
    from apps.publisher.engine import _blotato_extra
    acct = _make("blotato_facebook", {"blotato_account_id": "98432", "page_id": "PAGE7"})
    extra = {}
    _blotato_extra(acct, "blotato_facebook", extra)
    assert extra["blotato_account_id"] == "98432"
    assert extra["page_id"] == "PAGE7"


@pytest.mark.django_db
def test_blotato_extras_account_id_falls_back_to_platform_id():
    from apps.publisher.engine import _blotato_extra
    acct = _make("blotato_instagram", {})
    extra = {}
    _blotato_extra(acct, "blotato_instagram", extra)
    assert extra["blotato_account_id"] == "98432"
    assert "page_id" not in extra


@pytest.mark.django_db
def test_blotato_extras_injects_page_id_for_linkedin_company_page():
    """LinkedIn company-page accounts must get page_id in extra (was facebook-only),
    and the LinkedIn target must carry it as pageId so the post hits the org page."""
    from apps.publisher.engine import _blotato_extra
    from providers.blotato import BlotatoLinkedInProvider
    from providers.types import PublishContent

    acct = _make("blotato_linkedin", {"blotato_account_id": "18377", "page_id": "107605829"})
    extra = {}
    _blotato_extra(acct, "blotato_linkedin", extra)
    assert extra["page_id"] == "107605829"

    target = BlotatoLinkedInProvider()._build_target(PublishContent(text="x", extra=extra))
    assert target == {"targetType": "linkedin", "pageId": "107605829"}

    # Personal LinkedIn (no page_id) must NOT include pageId.
    personal = BlotatoLinkedInProvider()._build_target(PublishContent(text="x", extra={}))
    assert personal == {"targetType": "linkedin"}


def test_native_post_id_extraction():
    """Blotato analytics needs the native numeric post id from the publicUrl,
    not the submission UUID (which 500s). Instagram shortcodes -> None."""
    from providers.blotato import _native_post_id
    assert _native_post_id("https://linkedin.com/feed/update/urn:li:share:7478369059353550849") == "7478369059353550849"
    assert _native_post_id("https://x.com/i/status/1899999999999999999") == "1899999999999999999"
    assert _native_post_id("https://twitter.com/waii/status/1888888888888888888") == "1888888888888888888"
    assert _native_post_id("https://facebook.com/107605829/posts/456789012345") == "456789012345"
    assert _native_post_id("https://instagram.com/p/DAbc123/") is None
    assert _native_post_id("") is None
    assert _native_post_id(None) is None
