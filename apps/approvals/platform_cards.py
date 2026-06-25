"""Platform-styled email card renderer for approval-by-email.

``render_cards(post)`` iterates the post's PlatformPosts and returns a
concatenated HTML string of inline-styled cards — one per platform post.
All CSS is inline so email clients that strip <style> blocks still render
correctly.  Pure function; no DB writes.
"""

from __future__ import annotations

from apps.composer.models import Post

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
}

_DEFAULT_STYLE = ("Social", "#555555")


def _platform_meta(platform: str) -> tuple[str, str]:
    """Return (label, accent_color) for the given platform slug."""
    return _PLATFORM_STYLES.get(platform.lower(), _DEFAULT_STYLE)


def _card_html(label: str, color: str, handle: str, caption: str, thumbnail_url: str | None) -> str:
    """Render a single inline-styled card as an HTML string."""
    thumb_html = ""
    if thumbnail_url:
        thumb_html = (
            f'<div style="margin-bottom:8px;">'
            f'<img src="{thumbnail_url}" alt="media" '
            f'style="max-width:100%;border-radius:4px;display:block;" /></div>'
        )

    handle_html = ""
    if handle:
        handle_html = (
            f'<div style="font-size:12px;color:#888888;margin-bottom:8px;">'
            f'{handle}</div>'
        )

    # Escape caption for HTML display
    safe_caption = (
        caption
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
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
        f'</div>'
    )


def render_cards(post: Post) -> str:
    """Return an HTML string of platform-styled cards for all PlatformPosts on *post*.

    Iterates ``post.platform_posts.select_related("social_account")`` and emits
    one inline-styled ``<div>`` card per entry.  Returns an empty string if the
    post has no platform posts.  Pure function — no DB writes.
    """
    parts: list[str] = []

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

        # First media thumbnail: check platform_specific_media first
        thumbnail_url: str | None = None
        # (media lookup is a seam; thumbnails are advisory for email previews)

        parts.append(_card_html(label, color, handle, caption, thumbnail_url))

    return "".join(parts)
