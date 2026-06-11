"""Ghost (Nexus Brief) provider — publish to a Ghost site via the Admin API.

Auth is a single Admin API key (no per-user OAuth); a fresh JWT is signed per
request. Publishes human-authored content as a web Post (default) or an
email-only Newsletter (``extra['ghost_publish_as'] == 'newsletter'``).
"""
from __future__ import annotations

import html as _html

import httpx

from .base import SocialProvider
from .exceptions import PublishError
from .ghost_jwt import ghost_admin_jwt
from .types import (
    AccountProfile,
    AuthType,
    MediaType,
    PostType,
    PublishContent,
    PublishResult,
)

_TIMEOUT = 20.0
_HEADERS_VERSION = "v5.0"


class GhostProvider(SocialProvider):
    @property
    def platform_name(self) -> str:
        return "Ghost (Nexus Brief)"

    @property
    def auth_type(self) -> AuthType:
        return AuthType.API_KEY

    @property
    def max_caption_length(self) -> int:
        return 100000

    @property
    def supported_post_types(self) -> list[PostType]:
        return [PostType.TEXT, PostType.ARTICLE]

    @property
    def supported_media_types(self) -> list[MediaType]:
        return [MediaType.JPEG, MediaType.PNG]

    @property
    def required_scopes(self) -> list[str]:
        return []

    # -- helpers -------------------------------------------------------
    def _key(self) -> str:
        key = self.credentials.get("admin_api_key")
        if not key:
            raise PublishError("Ghost admin_api_key not configured")
        return key

    def _base(self) -> str:
        base = (self.credentials.get("base_url") or "").rstrip("/")
        if not base:
            raise PublishError("Ghost base_url not configured")
        return base

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Ghost {ghost_admin_jwt(self._key())}",
            "Content-Type": "application/json",
            "Accept-Version": _HEADERS_VERSION,
        }

    @staticmethod
    def _to_html(text: str) -> str:
        paras = [p for p in (text or "").split("\n") if p.strip()]
        return "".join(f"<p>{_html.escape(p)}</p>" for p in paras) or "<p></p>"

    # -- profile (connect validation) ----------------------------------
    def get_profile(self, access_token: str) -> AccountProfile:
        resp = httpx.get(
            f"{self._base()}/ghost/api/admin/site/",
            headers=self._auth_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            raise PublishError(f"Ghost validation failed ({resp.status_code}): {resp.text[:200]}")
        site = resp.json().get("site", {})
        return AccountProfile(
            platform_id=site.get("url", self._base()),
            name=site.get("title", "Ghost"),
            handle=None,
        )

    # -- publish -------------------------------------------------------
    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        title = (content.extra.get("title") or (content.text or "").split("\n", 1)[0] or "Untitled")[:255]
        excerpt = (content.text or "").strip()[:280]
        post_obj = {
            "title": title,
            "html": self._to_html(content.text),
            "custom_excerpt": excerpt,
            "status": "published",
            "tags": [{"name": "AfCEN"}],
        }
        mode = content.extra.get("ghost_publish_as", "post")
        url = f"{self._base()}/ghost/api/admin/posts/?source=html"
        if mode == "newsletter":
            slug = self.credentials.get("newsletter_slug")
            if not slug:
                raise PublishError("Newsletter publish needs a configured newsletter_slug")
            url = f"{self._base()}/ghost/api/admin/posts/?newsletter={slug}&source=html"
            post_obj["email_only"] = True
        resp = httpx.post(
            url,
            headers=self._auth_headers(),
            json={"posts": [post_obj]},
            timeout=_TIMEOUT,
        )
        if resp.status_code not in (200, 201):
            raise PublishError(f"Ghost publish failed ({resp.status_code}): {resp.text[:300]}")
        post = resp.json().get("posts", [{}])[0]
        return PublishResult(
            platform_post_id=post.get("id", ""),
            url=post.get("url"),
            extra={"ghost_publish_as": mode},
        )
