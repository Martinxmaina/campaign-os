"""Ghost (Nexus Brief) provider — publish to a Ghost site via the Admin API.

Auth is a single Admin API key (no per-user OAuth); a fresh JWT is signed per
request. Publishes human-authored content as a web Post (default) or an
email-only Newsletter (``extra['ghost_publish_as'] == 'newsletter'``).
"""
from __future__ import annotations

import html as _html
import re as _re
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
    PostMetrics,
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

    @staticmethod
    def _strip_tags(html_str: str) -> str:
        """Best-effort plain-text from an HTML fragment (for title/excerpt).

        Drops tags and collapses whitespace; unescapes entities so the derived
        title/excerpt read naturally. Never used for the post body itself.
        """
        no_tags = _re.sub(r"<[^>]+>", " ", html_str or "")
        text = _html.unescape(no_tags)
        return " ".join(text.split())

    def upload_image_bytes(self, content: bytes, filename: str = "image.jpg", content_type: str = "image/jpeg") -> str | None:
        """Store raw image bytes on Ghost; return the permanent Ghost URL or None.

        Used both by the composer (hybrid: re-host an inline article image the
        moment it's inserted, so the ``src`` never depends on an expiring
        presigned URL) and by :meth:`_rehost_images` at publish time. Best-effort:
        any failure returns ``None``.
        """
        try:
            # The upload endpoint is multipart/form-data — sign a JWT but do NOT
            # send the JSON Content-Type header (httpx sets the multipart one).
            headers = {
                "Authorization": f"Ghost {ghost_admin_jwt(self._key())}",
                "Accept-Version": _HEADERS_VERSION,
            }
            up = httpx.post(
                f"{self._base()}/ghost/api/admin/images/upload/",
                headers=headers,
                files={"file": (filename, content, content_type)},
                data={"purpose": "image"},
                timeout=_TIMEOUT,
            )
            if up.status_code not in (200, 201):
                return None
            images = up.json().get("images", [])
            return images[0].get("url") if images else None
        except Exception:  # noqa: BLE001 — best-effort
            return None

    def _upload_image(self, src: str) -> str | None:
        """Fetch an image by URL and store it on Ghost; return the stable URL.

        Our composer inserts ``<img>`` tags whose ``src`` points at our own
        media (often a *presigned* S3 URL that expires in ~1h). Ghost stores
        post HTML verbatim, so we must re-host each such image on Ghost via the
        Admin API ``/images/upload/`` endpoint and rewrite the ``src`` to the
        returned permanent Ghost URL before publishing. Best-effort: any failure
        returns ``None`` and the caller keeps the original src.
        """
        try:
            img_resp = httpx.get(src, timeout=_TIMEOUT, follow_redirects=True)
            if img_resp.status_code != 200:
                return None
            content_type = img_resp.headers.get("content-type", "image/jpeg")
            filename = (src.split("?", 1)[0].rsplit("/", 1)[-1]) or "image.jpg"
            return self.upload_image_bytes(img_resp.content, filename, content_type)
        except Exception:  # noqa: BLE001 — best-effort; keep the original src
            return None

    def _rehost_images(self, body_html: str) -> str:
        """Rewrite every ``<img src>`` in the HTML to a Ghost-hosted URL.

        Already-Ghost-hosted images (src under our base) are left untouched.
        """
        base = self._base()

        def _replace(match: "_re.Match[str]") -> str:
            whole, src = match.group(0), match.group(1)
            if not src or src.startswith(f"{base}/content/"):
                return whole
            new_url = self._upload_image(src)
            if not new_url:
                return whole
            return whole.replace(src, new_url, 1)

        return _re.sub(r'<img\b[^>]*?\bsrc=["\']([^"\']+)["\']', _replace, body_html)

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

    def get_post_metrics(self, access_token: str, post_id: str) -> PostMetrics:
        """Per-post metrics from the Ghost Admin API.

        Ghost records link ``clicks`` on every post, and — for posts SENT AS
        EMAIL to members — the newsletter ``reach`` (recipients) and ``opens``.
        Web-only posts have no ``email`` object, so reach/opens are 0 (Ghost only
        tracks those when a post is emailed to members). ``?include=email`` adds
        the email stats; ``count.clicks`` adds the click tally.
        """
        resp = httpx.get(
            f"{self._base()}/ghost/api/admin/posts/{post_id}/?include=email,count.clicks",
            headers=self._auth_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            raise PublishError(
                f"Ghost post metrics fetch failed ({resp.status_code}): {resp.text[:200]}"
            )
        post = (resp.json().get("posts") or [{}])[0]
        count = post.get("count") or {}
        email = post.get("email") or {}
        return PostMetrics(
            reach=int(email.get("email_count") or 0),  # members the newsletter reached
            clicks=int(count.get("clicks") or 0),  # link clicks on the post
            extra={"opens": int(email.get("opened_count") or 0)},  # email opens
        )

    # -- publish -------------------------------------------------------
    def publish_post(self, access_token: str, content: PublishContent) -> PublishResult:
        # Rich-editor path: the override caption is already HTML (the Ghost
        # channel's per-channel override). Publish it verbatim — do NOT escape
        # — and derive a sensible title/excerpt from its text content.
        is_html = (content.extra.get("body_format") == "html")
        if is_html:
            body_html = content.text or "<p></p>"
            # Re-host inline images on Ghost so they survive our presigned-URL
            # expiry (Ghost stores the HTML verbatim).
            if "<img" in body_html:
                body_html = self._rehost_images(body_html)
            plain = self._strip_tags(body_html)
            # The author's real title arrives as content.title (engine sets it from
            # effective_title). Only fall back to the body's first sentence when no
            # title was given — never override an explicit title.
            title = ((content.title or "").strip() or content.extra.get("title") or plain.split(". ", 1)[0] or "Untitled")[:255]
            excerpt = plain[:280]
        else:
            title = ((content.title or "").strip() or content.extra.get("title") or (content.text or "").split("\n", 1)[0] or "Untitled")[:255]
            excerpt = (content.text or "").strip()[:280]
            body_html = self._to_html(content.text)
        # A composer-authored subtitle (Ghost "custom excerpt") wins over the
        # auto-derived excerpt when present. Ghost caps custom_excerpt at 300.
        subtitle = (content.extra.get("subtitle") or "").strip()
        base_obj = {
            "title": title,
            "html": body_html,
            "custom_excerpt": subtitle[:300] if subtitle else excerpt,
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
