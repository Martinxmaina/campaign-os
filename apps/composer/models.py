"""Post Composer models (F-2.1) — core content creation entities.

Models:
    Post — The base content entity, scoped to a workspace.
    PlatformPost — Per-platform variant of a post (caption/media overrides).
    PostMedia — Media attachments with ordering and alt text.
    PostVersion — Immutable snapshots for version history.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.managers import WorkspaceScopedManager


class Post(models.Model):
    """A piece of content created in the composer.

    A Post holds the shared/base content. PlatformPost children hold
    per-platform overrides. Status flows through a state machine:
        draft → scheduled → publishing → published / partially_published / failed
    (With optional approval steps: pending_review, pending_client, approved,
     changes_requested, rejected.)
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_REVIEW = "pending_review", "Pending Review"
        PENDING_CLIENT = "pending_client", "Pending Client"
        APPROVED = "approved", "Approved"
        CHANGES_REQUESTED = "changes_requested", "Changes Requested"
        REJECTED = "rejected", "Rejected"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        PARTIALLY_PUBLISHED = "partially_published", "Partially Published"
        FAILED = "failed", "Failed"

    # Valid state transitions (from → set of allowed targets)
    VALID_TRANSITIONS = {
        "draft": {"pending_review", "scheduled", "publishing"},
        "pending_review": {"approved", "changes_requested", "rejected"},
        "approved": {"pending_client", "scheduled", "publishing"},
        "pending_client": {"approved", "changes_requested", "rejected"},
        "changes_requested": {"pending_review", "draft"},
        "rejected": {"draft", "pending_review"},
        "scheduled": {"publishing", "draft"},
        "publishing": {"published", "partially_published", "failed"},
        "partially_published": {"publishing"},  # manual retry
        "failed": {"publishing", "draft"},  # retry or revert to draft
    }

    # Status badge colors for calendar display
    STATUS_COLORS = {
        "draft": "gray",
        "pending_review": "orange",
        "pending_client": "amber",
        "approved": "teal",
        "changes_requested": "orange",
        "rejected": "red",
        "scheduled": "blue",
        "publishing": "indigo",
        "published": "green",
        "partially_published": "yellow",
        "failed": "red",
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="posts",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_posts",
    )

    # Content
    caption = models.TextField(blank=True, default="")
    first_comment = models.TextField(blank=True, default="")
    internal_notes = models.TextField(blank=True, default="")
    tags = models.JSONField(default=list, blank=True)

    # Status
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    # Scheduling
    scheduled_at = models.DateTimeField(blank=True, null=True, db_index=True)
    published_at = models.DateTimeField(blank=True, null=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "composer_post"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_at"], name="idx_post_status_sched"),
            models.Index(fields=["workspace", "status"], name="idx_post_ws_status"),
        ]

    def __str__(self):
        snippet = (self.caption[:50] + "...") if len(self.caption) > 50 else self.caption
        return f"Post({self.status}): {snippet or '(no caption)'}"

    def can_transition_to(self, new_status):
        """Check if a status transition is valid."""
        allowed = self.VALID_TRANSITIONS.get(self.status, set())
        return new_status in allowed

    def transition_to(self, new_status):
        """Transition to a new status, raising ValueError if invalid."""
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Invalid status transition: {self.status} → {new_status}. "
                f"Allowed: {self.VALID_TRANSITIONS.get(self.status, set())}"
            )
        self.status = new_status
        if new_status == "published":
            self.published_at = timezone.now()

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, "gray")

    @property
    def is_editable(self):
        """Whether the post can be edited in the composer."""
        return self.status in (
            "draft",
            "changes_requested",
            "rejected",
            "approved",
            "scheduled",
        )

    @property
    def is_schedulable(self):
        """Whether the post can be scheduled."""
        return self.status in ("draft", "approved")

    @property
    def caption_snippet(self):
        """First 100 characters of caption for preview."""
        if len(self.caption) <= 100:
            return self.caption
        return self.caption[:100] + "…"

    @property
    def platform_posts_summary(self):
        """Summary of target platforms."""
        return list(
            self.platform_posts.values_list("social_account__platform", flat=True)
        )


class PlatformPost(models.Model):
    """A per-platform variant of a Post.

    Created for each selected social account when composing. Holds
    optional caption/media overrides and tracks per-platform publish state.
    """

    class PublishStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="platform_posts",
    )
    social_account = models.ForeignKey(
        "social_accounts.SocialAccount",
        on_delete=models.CASCADE,
        related_name="platform_posts",
    )

    # Per-platform overrides (null = use base post values)
    platform_specific_caption = models.TextField(blank=True, null=True)
    platform_specific_media = models.JSONField(
        blank=True,
        null=True,
        help_text="JSON list of media asset IDs with platform-specific ordering/cropping.",
    )
    platform_specific_first_comment = models.TextField(blank=True, null=True)

    # Publishing state
    platform_post_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="The post ID on the platform after publishing.",
    )
    publish_status = models.CharField(
        max_length=20,
        choices=PublishStatus.choices,
        default=PublishStatus.PENDING,
    )
    publish_error = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(blank=True, null=True)
    retry_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "composer_platform_post"
        unique_together = [("post", "social_account")]

    def __str__(self):
        return f"PlatformPost({self.social_account.platform}): {self.publish_status}"

    @property
    def effective_caption(self):
        """Return platform-specific caption or fall back to base post caption."""
        if self.platform_specific_caption is not None:
            return self.platform_specific_caption
        return self.post.caption

    @property
    def effective_first_comment(self):
        """Return platform-specific first comment or fall back to base."""
        if self.platform_specific_first_comment is not None:
            return self.platform_specific_first_comment
        return self.post.first_comment

    @property
    def platform(self):
        return self.social_account.platform

    @property
    def char_limit(self):
        return self.social_account.char_limit

    @property
    def caption_length(self):
        return len(self.effective_caption)

    @property
    def is_over_limit(self):
        return self.caption_length > self.char_limit


class PostMedia(models.Model):
    """Media attachment on a post, with ordering and alt text."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="media_attachments",
    )
    media_asset = models.ForeignKey(
        "media_library.MediaAsset",
        on_delete=models.CASCADE,
        related_name="post_usages",
    )
    position = models.PositiveIntegerField(default=0, help_text="Ordering position in carousel.")
    alt_text = models.TextField(blank=True, default="")
    platform_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text='Per-platform crop/format overrides, e.g. {"instagram": {"crop": "4:5"}}',
    )

    class Meta:
        db_table = "composer_post_media"
        ordering = ["position"]
        unique_together = [("post", "media_asset")]

    def __str__(self):
        return f"PostMedia(pos={self.position}): {self.media_asset.filename}"


class PostVersion(models.Model):
    """Immutable snapshot of a post state for version history."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    snapshot = models.JSONField(
        help_text="Full post state at time of save (caption, media, platforms, etc.).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "composer_post_version"
        ordering = ["-version_number"]
        unique_together = [("post", "version_number")]

    def __str__(self):
        return f"PostVersion(v{self.version_number}) for {self.post_id}"
