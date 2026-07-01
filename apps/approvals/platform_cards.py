"""Platform-styled email card renderer for approval-by-email.

``render_cards(post)`` iterates the post's PlatformPosts and returns a
concatenated HTML string of inline-styled cards — one per platform post.
All CSS is inline so email clients that strip <style> blocks still render
correctly.  Pure function; no DB writes.
"""

from __future__ import annotations

import html as _html
import re

from django.utils.html import strip_tags


def _html_to_readable(html_str: str) -> str:
    """Down-convert an HTML fragment (e.g. a Ghost article body) to readable plain text.

    ponytail: no sanitizer dependency — block tags become line breaks, <br> too,
    list items get a bullet, the rest is stripped, and the CALLER escapes the
    result. The reviewer sees the readable article instead of raw <p>/<h2> tags,
    with zero XSS risk on the tokenized review page. The real Ghost post still
    renders fully formatted (the provider publishes with ?source=html).
    """
    s = re.sub(r"(?i)<li[^>]*>", "• ", html_str)
    s = re.sub(r"(?i)</(p|div|h[1-6]|li|blockquote|tr|ul|ol)>", "\n", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = strip_tags(s)
    s = _html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


# Per-platform display metadata: (label, accent_color_hex)
_PLATFORM_STYLES: dict[str, tuple[str, str]] = {
    "linkedin": ("LinkedIn", "#0A66C2"),
    "linkedin_personal": ("LinkedIn", "#0A66C2"),
    "linkedin_company": ("LinkedIn", "#0A66C2"),
    "twitter": ("X", "#000000"),
    "x": ("X", "#000000"),
    "instagram": ("Instagram", "#E1306C"),
    "instagram_login": ("Instagram", "#E1306C"),
    "facebook": ("Facebook", "#1877F2"),
    "threads": ("Threads", "#000000"),
    "bluesky": ("Bluesky", "#0085FF"),
    "tiktok": ("TikTok", "#010101"),
    "youtube": ("YouTube", "#FF0000"),
    "pinterest": ("Pinterest", "#E60023"),
    "mastodon": ("Mastodon", "#6364FF"),
    "ghost": ("Ghost", "#15171A"),
    "google_business": ("Google Business", "#4285F4"),
    # Blotato multi-platform wrappers
    "blotato_instagram": ("Instagram", "#E1306C"),
    "blotato_facebook": ("Facebook", "#1877F2"),
    "blotato_threads": ("Threads", "#000000"),
    "blotato_bluesky": ("Bluesky", "#0085FF"),
    "blotato_linkedin": ("LinkedIn", "#0A66C2"),
    "blotato_twitter": ("X / Twitter", "#000000"),
}

_DEFAULT_STYLE = ("Social", "#555555")


def _platform_meta(platform: str) -> tuple[str, str]:
    """Return (label, accent_color) for the given platform slug."""
    return _PLATFORM_STYLES.get(platform.lower(), _DEFAULT_STYLE)


def _card_html(label: str, color: str, handle: str, caption: str, thumbnail_url: str | None, is_html: bool = False) -> str:
    """Render a single inline-styled card as an HTML string.

    ``is_html=True`` (Ghost) means the caption IS an HTML article body: show it as
    readable text rather than escaped raw tags.
    """
    thumb_html = ""
    if thumbnail_url:
        # quote=True escapes " so a crafted URL cannot break out of the src attribute.
        safe_url = _html.escape(thumbnail_url, quote=True)
        thumb_html = (
            f'<div style="margin-bottom:8px;">'
            f'<img src="{safe_url}" alt="media" '
            f'style="max-width:100%;border-radius:4px;display:block;" /></div>'
        )

    handle_html = ""
    if handle:
        # quote=True escapes " so a crafted handle cannot break an attribute.
        safe_handle = _html.escape(handle, quote=True)
        handle_html = (
            f'<div style="font-size:12px;color:#888888;margin-bottom:8px;">'
            f'{safe_handle}</div>'
        )

    # Ghost's caption is an HTML article body → show readable text (not raw tags).
    # Everything is escaped for safe HTML text-node display either way.
    display_text = _html_to_readable(caption) if is_html else caption
    safe_caption = _html.escape(display_text, quote=True)
    note_html = ""
    if is_html:
        note_html = (
            '<div style="font-size:11px;color:#9ca3af;margin-top:8px;">'
            'Publishes as a formatted article on Ghost.</div>'
        )

    return (
        f'<div style="font-family:sans-serif;border:1px solid #e5e7eb;border-radius:8px;'
        f'padding:16px;margin-bottom:16px;max-width:560px;">'
        f'<div style="display:inline-block;background:{color};color:#ffffff;'
        f'font-size:11px;font-weight:700;letter-spacing:0.05em;padding:3px 8px;'
        f'border-radius:4px;margin-bottom:10px;">{label}</div>'
        f'{handle_html}'
        f'{thumb_html}'
        f'<div style="font-size:14px;color:#111827;line-height:1.5;'
        f'white-space:pre-wrap;">{safe_caption}</div>'
        f'{note_html}'
        f'</div>'
    )


def render_cards(post) -> str:
    """Return an HTML string of platform-styled cards for all PlatformPosts on *post*.

    Iterates ``post.platform_posts.select_related("social_account")`` and emits
    one inline-styled ``<div>`` card per entry.  Returns an empty string if the
    post has no platform posts.  Pure function — no DB writes.
    """
    parts: list[str] = []

    # Resolve the thumbnail ONCE before the per-PlatformPost loop to avoid N+1 queries.
    thumbnail_url: str | None = None
    first_attachment = (
        post.media_attachments.select_related("media_asset").order_by("position").first()
    )
    if first_attachment:
        asset = first_attachment.media_asset
        if asset.thumbnail:
            thumbnail_url = asset.thumbnail.url
        elif asset.file:
            thumbnail_url = asset.file.url

    for pp in post.platform_posts.select_related("social_account").all():
        sa = pp.social_account
        platform = sa.platform if sa else ""
        label, color = _platform_meta(platform)

        # Prefer handle; fall back to account name
        handle = ""
        if sa:
            handle = sa.account_handle or sa.account_name or ""

        # Caption: use platform-specific override if set, else base post caption
        caption = pp.platform_specific_caption if pp.platform_specific_caption else post.caption

        # Ghost's caption is an HTML article body — render it readably, not as raw tags.
        is_html = platform.lower() == "ghost"

        parts.append(_card_html(label, color, handle, caption, thumbnail_url, is_html=is_html))

    return "".join(parts)
