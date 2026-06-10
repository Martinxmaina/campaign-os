"""Per-platform credential field specifications for the in-app credentials form.

Each platform's OAuth integration reads specific keys from the stored
``PlatformCredential.credentials`` JSON. This map tells the form which fields
to render and validate so the saved dict matches what the provider expects.
"""

from __future__ import annotations

# Ordered so the most useful channels appear first in the UI.
PLATFORM_FIELDS: dict[str, dict] = {
    "linkedin_personal": {
        "label": "LinkedIn (Personal Profile)",
        "help": "developers.linkedin.com → your app → Auth tab. Add redirect URI: "
                "/social-accounts/callback/linkedin_personal/",
        "fields": [
            ("client_id", "Client ID", "text"),
            ("client_secret", "Client Secret", "password"),
        ],
    },
    "linkedin_company": {
        "label": "LinkedIn (Company Page)",
        "help": "Same app as personal, or a Community Management API app. Redirect URI: "
                "/social-accounts/callback/linkedin_company/",
        "fields": [
            ("client_id", "Client ID", "text"),
            ("client_secret", "Client Secret", "password"),
        ],
    },
    "twitter": {
        "label": "X / Twitter",
        "help": "developer.twitter.com → Project → OAuth 2.0. Redirect URI: "
                "/social-accounts/callback/twitter/",
        "fields": [
            ("client_id", "Client ID", "text"),
            ("client_secret", "Client Secret", "password"),
        ],
    },
    "facebook": {
        "label": "Facebook",
        "help": "developers.facebook.com → your app → Settings → Basic. Redirect URI: "
                "/social-accounts/callback/facebook/",
        "fields": [
            ("app_id", "App ID", "text"),
            ("app_secret", "App Secret", "password"),
        ],
    },
    "instagram": {
        "label": "Instagram",
        "help": "Uses the same Meta app as Facebook. Redirect URI: "
                "/social-accounts/callback/instagram/",
        "fields": [
            ("app_id", "App ID", "text"),
            ("app_secret", "App Secret", "password"),
        ],
    },
    "youtube": {
        "label": "YouTube",
        "help": "console.cloud.google.com → OAuth client (YouTube Data API v3). Redirect URI: "
                "/social-accounts/callback/youtube/",
        "fields": [
            ("client_id", "Client ID", "text"),
            ("client_secret", "Client Secret", "password"),
        ],
    },
    "threads": {
        "label": "Threads",
        "help": "Uses the same Meta app. Redirect URI: "
                "/social-accounts/callback/threads/",
        "fields": [
            ("app_id", "App ID", "text"),
            ("app_secret", "App Secret", "password"),
        ],
    },
}


def field_keys(platform: str) -> list[str]:
    """Return the credential dict keys for a platform."""
    spec = PLATFORM_FIELDS.get(platform, {})
    return [f[0] for f in spec.get("fields", [])]
