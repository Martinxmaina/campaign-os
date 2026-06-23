from providers.exceptions import BlotatoStillPublishing, ProviderError


def test_still_publishing_carries_submission_id():
    err = BlotatoStillPublishing("sub_123", platform="Instagram (Blotato)")
    assert isinstance(err, ProviderError)
    assert err.submission_id == "sub_123"
    assert "sub_123" in str(err)
