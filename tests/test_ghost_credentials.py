def test_ghost_fields_declared():
    from apps.credentials.platform_fields import PLATFORM_FIELDS, required_field_keys
    assert "ghost" in PLATFORM_FIELDS
    req = required_field_keys("ghost")
    assert "admin_api_key" in req and "base_url" in req
    assert "newsletter_slug" not in req  # optional
