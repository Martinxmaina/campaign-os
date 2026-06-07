"""X (Twitter) provider implementation (X API v2).

Posting uses the v2 manage-Tweets endpoint
(``POST https://api.twitter.com/2/tweets``) with an OAuth2 user-context
bearer token. Media upload (v1.1 ``media/upload``) is wired through the
v2 ``media`` payload but live OAuth/media is deferred until creds are
available; text posting is the supported path today.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .base import REQUEST_TIMEOUT, SocialProvider
from .exceptions import APIError, PublishError, RateLimitError
from .types import (
    AccountProfile,
    AuthType,
    MediaType,
    PostType,
    PublishContent,
    PublishResult,
    RateLimitConfig,
)

logger = logging.getLogger(__name__)

API_BASE = "https://api.twitter.com/2"
TWEETS_URL = f"{API_BASE}/tweets"
USERS_ME_URL = f"{API_BASE}/users/me"


class TwitterProvider(SocialProvider):
    """X (Twitter) provider backed by the X API v2."""

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    def platform_name(self) -> str:
        return "X"

    @property
    def auth_type(self) -> AuthType:
        return AuthType.OAUTH2

    @property
    def max_caption_length(self) -> int:
        return 280

    @property
    def supported_post_types(self) -> list[PostType]:
        return [PostType.TEXT, PostType.IMAGE, PostType.VIDEO]

    @property
    def supported_media_types(self) -> list[MediaType]:
        return [MediaType.JPEG, MediaType.PNG, MediaType.GIF, MediaType.MP4]

    @property
    def required_scopes(self) -> list[str]:
        return ["tweet.read", "tweet.write", "users.read", "offline.access"]

    @property
    def rate_limits(self) -> RateLimitConfig:
        # X API v2 free/basic tiers cap Tweet creation tightly.
        return RateLimitConfig(
            requests_per_hour=50,
            requests_per_day=50,
            publish_per_day=50,
        )

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def get_profile(self, access_token: str) -> AccountProfile:
        resp = self._request(
            "GET",
            USERS_ME_URL,
            access_token=access_token,
            params={"user.fields": "profile_image_url,public_metrics,username,name"},
        )
        data = resp.json().get("data", {})
        metrics = data.get("public_metrics", {})
        return AccountProfile(
            platform_id=data.get("id", ""),
            name=data.get("name", ""),
            handle=data.get("username"),
            avatar_url=data.get("profile_image_url"),
            follower_count=metrics.get("followers_count", 0),
            extra=data,
        )

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        body: dict = {"text": content.text}

        media_ids = content.extra.get("media_ids")
        if media_ids:
            body["media"] = {"media_ids": media_ids}

        resp = self._post_tweet(access_token, body)
        data = resp.json().get("data", {})
        tweet_id = data.get("id")
        if not tweet_id:
            raise PublishError(
                "X API did not return a Tweet id",
                platform=self.platform_name,
                raw_response=resp.json() if self._is_json(resp) else {},
            )
        return PublishResult(
            platform_post_id=tweet_id,
            url=self._tweet_url(content, tweet_id),
            extra={"data": data},
        )

    def _post_tweet(self, access_token: str, body: dict) -> httpx.Response:
        """POST a Tweet, mapping X API errors to the provider exceptions.

        Uses ``httpx.Client.post`` directly (rather than the base ``_request``
        helper) because the X v2 manage-Tweets endpoint takes a JSON body on a
        dedicated POST.
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.post(TWEETS_URL, headers=headers, json=body)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            logger.error("X API 429 response: %s", response.text[:1000])
            raise RateLimitError(
                f"Rate limit exceeded for {self.platform_name}: {response.text[:500]}",
                retry_after=int(retry_after) if retry_after else None,
                platform=self.platform_name,
                raw_response=self._safe_json(response),
            )

        if response.status_code >= 400:
            raise APIError(
                f"{self.platform_name} API error {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
                platform=self.platform_name,
                raw_response=self._safe_json(response),
            )

        return response

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def get_account_metrics(self, access_token: str, date_range: tuple[datetime, datetime]):
        raise NotImplementedError(
            "X account analytics require the paid v2 metrics endpoints; not yet wired."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_json(response: httpx.Response) -> bool:
        try:
            response.json()
            return True
        except Exception:
            return False

    def _tweet_url(self, content: PublishContent, tweet_id: str) -> str | None:
        handle = content.extra.get("handle")
        if handle:
            return f"https://x.com/{handle}/status/{tweet_id}"
        return f"https://x.com/i/web/status/{tweet_id}"
