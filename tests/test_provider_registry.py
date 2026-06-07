from providers import PROVIDER_REGISTRY

KEEP = {"facebook", "instagram", "instagram_login",
        "linkedin_personal", "linkedin_company", "youtube", "threads"}
REMOVE = {"tiktok", "pinterest", "google_business", "mastodon", "bluesky"}

def test_registry_keeps_only_supported():
    keys = set(PROVIDER_REGISTRY)
    assert KEEP <= keys
    assert keys & REMOVE == set()
