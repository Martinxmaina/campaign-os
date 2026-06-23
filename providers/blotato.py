"""Blotato multi-platform publishing provider (add-on family).

Blotato (https://backend.blotato.com/v2) publishes to many networks behind a
single workspace API key. Accounts are connected in Blotato's dashboard and
referenced by accountId. One BlotatoProvider base + per-target subclasses
registered as ``blotato_<target>``. The engine injects per-account data
(blotato_account_id, page_id) via ``content.extra``. Publishing is async:
submit to POST /posts, poll GET /posts/{id}; on timeout raise
BlotatoStillPublishing so the engine parks the post for the reconcile task.
"""
from __future__ import annotations

import logging
import os
import time

from django.conf import settings

from .base import SocialProvider
from .exceptions import BlotatoStillPublishing, PublishError
from .types import AccountProfile, AuthType, MediaType, PostType, PublishContent, PublishResult

logger = logging.getLogger(__name__)


def _api_base() -> str:
    return getattr(settings, "BLOTATO_API_BASE", "https://backend.blotato.com/v2").rstrip("/")


class BlotatoProvider(SocialProvider):
    """Base for all Blotato targets. Subclasses set ``target_type`` + metadata."""

    target_type: str = ""
    _label: str = "Blotato"
    _max_caption: int = 2200

    @property
    def platform_name(self) -> str:
        return self._label

    @property
    def auth_type(self) -> AuthType:
        return AuthType.API_KEY

    @property
    def max_caption_length(self) -> int:
        return self._max_caption

    @property
    def supported_post_types(self) -> list[PostType]:
        return [PostType.TEXT, PostType.IMAGE, PostType.VIDEO]

    @property
    def supported_media_types(self) -> list[MediaType]:
        return [MediaType.JPEG, MediaType.PNG, MediaType.GIF, MediaType.MP4, MediaType.MOV]

    @property
    def required_scopes(self) -> list[str]:
        return []

    # Blotato manages each network's connection health on its side; our health
    # signal is publish success/failure, so don't fail the account on a profile
    # probe that can't see the per-account key in the health path.
    def validate_token(self, access_token: str) -> bool:
        return True

    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        api_key = self.credentials.get("api_key", "")
        if not api_key:
            raise PublishError("Blotato API key is not configured", platform=self.platform_name)
        return {"blotato-api-key": api_key}

    def get_profile(self, access_token: str) -> AccountProfile:
        resp = self._request("GET", f"{_api_base()}/users/me/accounts", headers=self._headers())
        for acct in resp.json().get("items", []):
            if str(acct.get("id")) == str(access_token):
                return AccountProfile(platform_id=str(acct["id"]),
                                      name=acct.get("fullname", ""), handle=acct.get("username"))
        return AccountProfile(platform_id=str(access_token), name="", handle=None)

    def _resolve_media_urls(self, content: PublishContent) -> list[str]:
        # Prefer already-public URLs; otherwise upload local files via /media.
        if content.media_urls:
            return list(content.media_urls)
        urls: list[str] = []
        for path in content.media_files or []:
            r = self._request("POST", f"{_api_base()}/media",
                              headers=self._headers(), json={"filename": os.path.basename(path)})
            data = r.json()
            with open(path, "rb") as fh:
                self._request("PUT", data["presignedUrl"], data=fh.read())
            urls.append(data["publicUrl"])
        return urls

    def _build_target(self, content: PublishContent) -> dict:
        return {"targetType": self.target_type}

    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        account_id = content.extra.get("blotato_account_id") or access_token
        if not account_id:
            raise PublishError("Missing Blotato account id", platform=self.platform_name)
        media_urls = self._resolve_media_urls(content)
        body = {
            "post": {
                "accountId": str(account_id),
                "content": {
                    "text": content.text or "",
                    "mediaUrls": media_urls,
                    "platform": self.target_type,
                },
                "target": self._build_target(content),
            }
        }
        resp = self._request("POST", f"{_api_base()}/posts", headers=self._headers(), json=body)
        data = resp.json()
        submission_id = str(data.get("postSubmissionId") or data.get("id") or "")
        if not submission_id:
            raise PublishError(f"Blotato returned no submission id: {resp.text[:300]}",
                               platform=self.platform_name)
        return self._poll_until_done(submission_id)

    def check_status(self, submission_id: str) -> dict:
        """One status read — used by publish polling and the reconcile task."""
        return self._request("GET", f"{_api_base()}/posts/{submission_id}",
                             headers=self._headers()).json()

    def _poll_until_done(self, submission_id: str) -> PublishResult:
        timeout = getattr(settings, "BLOTATO_PUBLISH_TIMEOUT", 30)
        interval = getattr(settings, "BLOTATO_POLL_INTERVAL", 2)
        deadline = time.monotonic() + timeout
        while True:
            data = self.check_status(submission_id)
            status = (data.get("status") or "").lower()
            if status == "published":
                return PublishResult(platform_post_id=submission_id,
                                     url=data.get("publicUrl"), extra=data)
            if status == "failed":
                raise PublishError(data.get("errorMessage") or "Blotato publish failed",
                                   platform=self.platform_name, raw_response=data)
            if time.monotonic() >= deadline:
                raise BlotatoStillPublishing(submission_id, platform=self.platform_name)
            time.sleep(interval)


class BlotatoInstagramProvider(BlotatoProvider):
    target_type = "instagram"
    _label = "Instagram (Blotato)"
    _max_caption = 2200


class BlotatoFacebookProvider(BlotatoProvider):
    target_type = "facebook"
    _label = "Facebook (Blotato)"
    _max_caption = 63206

    def _build_target(self, content: PublishContent) -> dict:
        target = {"targetType": "facebook"}
        page_id = content.extra.get("page_id")
        if page_id:
            target["pageId"] = page_id
        return target


class BlotatoThreadsProvider(BlotatoProvider):
    target_type = "threads"
    _label = "Threads (Blotato)"
    _max_caption = 500

    def _build_target(self, content: PublishContent) -> dict:
        target = {"targetType": "threads"}
        reply_control = content.extra.get("reply_control")
        if reply_control:
            target["replyControl"] = reply_control
        return target


class BlotatoBlueskyProvider(BlotatoProvider):
    target_type = "bluesky"
    _label = "Bluesky (Blotato)"
    _max_caption = 300


class BlotatoLinkedInProvider(BlotatoProvider):
    target_type = "linkedin"
    _label = "LinkedIn (Blotato)"
    _max_caption = 3000
