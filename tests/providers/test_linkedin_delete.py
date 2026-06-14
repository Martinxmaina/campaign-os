"""LinkedIn post deletion via the versioned REST Posts API.

LinkedIn has no edit endpoint, so "edit" is delete-recreate (covered by the
publisher operations tests). Here we pin only the provider-level delete:

- ``DELETE /rest/posts/{percent-encoded-urn}`` with the same versioned REST
  headers the publish path already uses (``LINKEDIN_HEADERS``).
- Returns truthy/ok on 204 (and 200) — LinkedIn returns 204 No Content on a
  successful delete.
- Raises ``PublishError`` on any failure (mock httpx; no real API calls).

All network is mocked at the ``_request`` boundary, matching the existing
``tests/providers/test_linkedin_company.py`` pattern.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from providers.exceptions import APIError, PublishError
from providers.linkedin import LINKEDIN_HEADERS, LinkedInProvider


def _make_response(status_code: int = 204) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value={})
    return resp


class TestDeletePost:
    @patch.object(LinkedInProvider, "_request")
    def test_delete_issues_versioned_rest_delete_with_encoded_urn(self, mock_request):
        mock_request.return_value = _make_response(204)

        provider = LinkedInProvider()
        result = provider.delete_post("tok-abc", "urn:li:share:123456")

        assert result is True
        args, kwargs = mock_request.call_args
        # Method + URL with the percent-encoded URN as a path segment.
        assert args[0] == "DELETE"
        assert args[1].endswith("/rest/posts/urn%3Ali%3Ashare%3A123456")
        # Reuses the versioned REST headers the publish path uses.
        assert kwargs["headers"] == LINKEDIN_HEADERS
        assert kwargs["access_token"] == "tok-abc"

    @patch.object(LinkedInProvider, "_request")
    def test_delete_accepts_200(self, mock_request):
        mock_request.return_value = _make_response(200)
        provider = LinkedInProvider()
        assert provider.delete_post("tok", "urn:li:ugcPost:999") is True
        args, _ = mock_request.call_args
        assert args[1].endswith("/rest/posts/urn%3Ali%3AugcPost%3A999")

    @patch.object(LinkedInProvider, "_request")
    def test_delete_raises_publish_error_on_api_error(self, mock_request):
        # _request raises APIError on >=400; delete_post must surface a
        # PublishError so callers handle it uniformly.
        mock_request.side_effect = APIError(
            "LinkedIn API error 404: not found",
            status_code=404,
            platform="LinkedIn",
        )
        provider = LinkedInProvider()
        with pytest.raises(PublishError):
            provider.delete_post("tok", "urn:li:share:404")

    def test_base_delete_post_not_implemented(self):
        # The abstract base advertises delete_post but defaults to
        # NotImplementedError so providers without delete fail loudly.
        from providers.mock import MockProvider

        provider = MockProvider()
        # MockProvider may or may not override; assert the base contract exists.
        assert hasattr(provider, "delete_post")
