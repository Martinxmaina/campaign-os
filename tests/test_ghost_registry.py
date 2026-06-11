def test_get_provider_returns_ghost():
    from providers import get_provider
    from providers.ghost import GhostProvider
    p = get_provider("ghost", {"admin_api_key": "a:bb", "base_url": "https://x.ghost.io"})
    assert isinstance(p, GhostProvider)
