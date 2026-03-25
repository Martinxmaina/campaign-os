"""Social Account models (F-2.5) — connected platform accounts per workspace."""

import uuid

from django.conf import settings
from django.db import models

from apps.common.encryption import EncryptedJSONField
from apps.common.managers import WorkspaceScopedManager


class SocialAccount(models.Model):
    """A connected social media account within a workspace.

    Stores OAuth tokens and account metadata. Each account represents
    one platform profile/page connected to one workspace.
    """

    class Platform(models.TextChoices):
        FACEBOOK = "facebook", "Facebook"
        INSTAGRAM = "instagram", "Instagram"
        LINKEDIN = "linkedin", "LinkedIn"
        TIKTOK = "tiktok", "TikTok"
        YOUTUBE = "youtube", "YouTube"
        PINTEREST = "pinterest", "Pinterest"
        THREADS = "threads", "Threads"
        BLUESKY = "bluesky", "Bluesky"
        GOOGLE_BUSINESS = "google_business", "Google Business Profile"
        MASTODON = "mastodon", "Mastodon"

    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        TOKEN_EXPIRING = "token_expiring", "Token Expiring"
        DISCONNECTED = "disconnected", "Disconnected"
        ERROR = "error", "Error"

    # Platform-specific character limits for captions
    PLATFORM_CHAR_LIMITS = {
        "facebook": 63206,
        "instagram": 2200,
        "linkedin": 3000,
        "tiktok": 2200,
        "youtube": 5000,
        "pinterest": 500,
        "threads": 500,
        "bluesky": 300,
        "google_business": 1500,
        "mastodon": 500,
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="social_accounts",
    )
    platform = models.CharField(max_length=30, choices=Platform.choices)
    platform_account_id = models.CharField(
        max_length=255,
        help_text="The unique account ID on the platform (e.g., page ID, profile ID).",
    )
    account_name = models.CharField(max_length=255, help_text="Display name on the platform.")
    account_handle = models.CharField(max_length=255, blank=True, default="")
    avatar_url = models.URLField(blank=True, default="")
    follower_count = models.PositiveIntegerField(default=0)

    # OAuth tokens — encrypted at rest
    access_token = EncryptedJSONField(
        default=dict,
        help_text="Encrypted access token and related auth data.",
    )
    refresh_token = EncryptedJSONField(
        default=dict,
        blank=True,
        help_text="Encrypted refresh token.",
    )
    token_expires_at = models.DateTimeField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONNECTED,
    )
    status_message = models.TextField(blank=True, default="")

    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="connected_social_accounts",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "social_accounts_social_account"
        unique_together = [("workspace", "platform", "platform_account_id")]

    def __str__(self):
        return f"{self.account_name} ({self.get_platform_display()})"

    @property
    def char_limit(self):
        """Return the character limit for this account's platform."""
        return self.PLATFORM_CHAR_LIMITS.get(self.platform, 5000)

    @property
    def platform_icon(self):
        """Return a platform icon identifier."""
        icons = {
            "facebook": "fb",
            "instagram": "ig",
            "linkedin": "li",
            "tiktok": "tt",
            "youtube": "yt",
            "pinterest": "pi",
            "threads": "th",
            "bluesky": "bs",
            "google_business": "gb",
            "mastodon": "ma",
        }
        return icons.get(self.platform, "??")
