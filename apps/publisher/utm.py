"""UTM tagging for outbound links in social captions.

Applied at dispatch (after the authoritative compliance gate) so each platform
gets the correct ``utm_source`` and the gate still hashes the human-authored
text. Plain-text/social only — Ghost article HTML is left untouched.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.utils.text import slugify

# Match bare http(s) URLs in plain text. Trailing sentence punctuation is
# trimmed off the match and re-appended so we don't capture it into the URL.
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_TRAILING = ".,!?;:)]}\"'"


def _source_for(platform: str) -> str:
    """utm_source from a platform key (drop the 'blotato_' transport prefix)."""
    p = (platform or "").replace("blotato_", "").strip()
    return p or "social"


def apply_utm(text: str, platform: str, campaign: str) -> str:
    """Add utm_source/medium/campaign to every http(s) URL in ``text``.

    Idempotent: a URL that already carries ``utm_source`` is left as-is.
    Existing query params and fragments are preserved.
    """
    if not text:
        return text
    source = _source_for(platform)
    camp = slugify(campaign or "") or "organic"

    def _rewrite(match: "re.Match[str]") -> str:
        url = match.group(0)
        trail = ""
        while url and url[-1] in _TRAILING:
            trail = url[-1] + trail
            url = url[:-1]
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        if "utm_source" in query:  # already tagged — don't double-tag
            return url + trail
        query["utm_source"] = source
        query["utm_medium"] = "social"
        query["utm_campaign"] = camp
        tagged = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        return tagged + trail

    return _URL_RE.sub(_rewrite, text)
