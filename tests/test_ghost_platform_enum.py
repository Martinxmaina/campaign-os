def test_ghost_platform_registered():
    from apps.credentials.models import PlatformCredential
    assert PlatformCredential.Platform.GHOST == "ghost"


def test_api_key_auth_type_exists():
    from providers.types import AuthType
    assert AuthType.API_KEY.value == "api_key"


def test_ghost_char_limit_present():
    from apps.social_accounts.models import SocialAccount
    assert SocialAccount.PLATFORM_CHAR_LIMITS.get("ghost", 0) >= 50000
