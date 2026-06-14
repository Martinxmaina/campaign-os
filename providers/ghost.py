"""Ghost (Nexus Brief) provider — publish to a Ghost site via the Admin API.

Auth is a single Admin API key (no per-user OAuth); a fresh JWT is signed per
request. Publishes human-authored content as a web Post (default) or an
email-only Newsletter (``extra['ghost_publish_as'] == 'newsletter'``).
"""
from __future__ import annotations

import html as _html
from datetime import datetime

import httpx

from .base import SocialProvider
from .exceptions import PublishError
from .ghost_jwt import ghost_admin_jwt
from .types import (
    AccountMetrics,
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
    # The members endpoint returns a single lifetime total, not a per-day
    # delta — so the sync layer must write only today's snapshot, never replay
    # the same total into past dates as fabricated history.
    account_metrics_supports_date_range = False

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

    # -- analytics -----------------------------------------------------
    def get_account_metrics(
        self, access_token: str, date_range: tuple[datetime, datetime]
    ) -> AccountMetrics:
        """Subscriber (member) count from the Ghost Admin API.

        Ghost exposes the member total via the pagination block of the
        members list — fetching one row is enough to read
        ``meta.pagination.total``. There is no per-day member-growth endpoint
        in the Admin API, so this is a lifetime snapshot (hence
        ``account_metrics_supports_date_range = False``). We surface it as both
        ``followers`` (the AccountMetrics shape other providers use) and
        ``extra['subscribers']`` (the catalog metric the analytics UI queries).
        """
        resp = httpx.get(
            f"{self._base()}/ghost/api/admin/members/?limit=1",
            headers=self._auth_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            raise PublishError(f"Ghost members fetch failed ({resp.status_code}): {resp.text[:200]}")
        total = (resp.json().get("meta", {}).get("pagination", {}) or {}).get("total")
        count = int(total) if total is not None else 0
        return AccountMetrics(followers=count, extra={"subscribers": count})

    # -- publish -------------------------------------------------------
    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        title = (content.extra.get("title") or (content.text or "").split("\n", 1)[0] or "Untitled")[:255]
        excerpt = (content.text or "").strip()[:280]
        base_obj = {
            "title": title,
            "html": self._to_html(content.text),
            "custom_excerpt": excerpt,
            "tags": [{"name": "AfCEN"}],
        }
        mode = content.extra.get("ghost_publish_as", "post")
        if mode == "newsletter":
            return self._publish_newsletter(base_obj, mode)
        return self._publish_web(base_obj, mode)

    def _publish_web(self, base_obj: dict, mode: str) -> PublishResult:
        """One-step web Post: create directly as published."""
        url = f"{self._base()}/ghost/api/admin/posts/?source=html"
        resp = httpx.post(url, headers=self._auth_headers(),
                          json={"posts": [{**base_obj, "status": "published"}]}, timeout=_TIMEOUT)
        if resp.status_code not in (200, 201):
            raise PublishError(f"Ghost publish failed ({resp.status_code}): {resp.text[:300]}")
        post = resp.json().get("posts", [{}])[0]
        return PublishResult(platform_post_id=post.get("id", ""), url=post.get("url"),
                             extra={"ghost_publish_as": mode})

    def _publish_newsletter(self, base_obj: dict, mode: str) -> PublishResult:
        """Two-step email-only send (docs/ghost.md §4.1-4.2): the newsletter
        relation must exist at draft creation, so create the draft WITH the
        newsletter slug in the URL, then PUT it to published. A one-step publish
        risks ``500 does not have a newsletter relation`` / no email sent."""
        slug = self.credentials.get("newsletter_slug")
        if not slug:
            raise PublishError("Newsletter publish needs a configured newsletter_slug")
        base = self._base()
        nl = f"newsletter={slug}&source=html"

        # Step 1: create draft with the newsletter relation attached.
        draft_resp = httpx.post(
            f"{base}/ghost/api/admin/posts/?{nl}",
            headers=self._auth_headers(),
            json={"posts": [{**base_obj, "status": "draft", "email_only": True}]},
            timeout=_TIMEOUT,
        )
        if draft_resp.status_code not in (200, 201):
            raise PublishError(f"Ghost draft failed ({draft_resp.status_code}): {draft_resp.text[:300]}")
        draft = draft_resp.json().get("posts", [{}])[0]
        post_id, updated_at = draft.get("id", ""), draft.get("updated_at")
        if not post_id:
            raise PublishError("Ghost draft returned no post id")

        # Step 2: publish the draft as email-only (Ghost requires the prior updated_at).
        pub_resp = httpx.put(
            f"{base}/ghost/api/admin/posts/{post_id}/?{nl}",
            headers=self._auth_headers(),
            json={"posts": [{"updated_at": updated_at, "status": "published", "email_only": True}]},
            timeout=_TIMEOUT,
        )
        if pub_resp.status_code not in (200, 201):
            raise PublishError(f"Ghost email publish failed ({pub_resp.status_code}): {pub_resp.text[:300]}")
        post = pub_resp.json().get("posts", [{}])[0]
        return PublishResult(platform_post_id=post.get("id", post_id), url=post.get("url"),
                             extra={"ghost_publish_as": mode})
