"""Media Library models (F-6.1) — media asset storage and management."""

import uuid

from django.conf import settings
from django.db import models

from apps.common.managers import WorkspaceScopedManager


class MediaAsset(models.Model):
    """A media file (image, video, GIF) uploaded to a workspace's media library.

    Stores the original file plus processed variants for different platforms.
    """

    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        GIF = "gif", "GIF"
        DOCUMENT = "document", "Document"

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="media_assets",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_media",
    )

    # File info
    file = models.FileField(upload_to="media_library/%Y/%m/")
    filename = models.CharField(max_length=255)
    media_type = models.CharField(max_length=20, choices=MediaType.choices)
    mime_type = models.CharField(max_length=100, blank=True, default="")
    file_size = models.PositiveBigIntegerField(default=0, help_text="File size in bytes.")

    # Image/video dimensions
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    duration = models.FloatField(default=0, help_text="Video duration in seconds.")

    # Thumbnail for videos and large images
    thumbnail = models.ImageField(upload_to="media_library/thumbs/%Y/%m/", blank=True)

    # Metadata
    alt_text = models.TextField(blank=True, default="")
    title = models.CharField(max_length=255, blank=True, default="")
    tags = models.JSONField(default=list, blank=True)

    # Attribution for stock media
    source = models.CharField(max_length=50, blank=True, default="", help_text="e.g., 'upload', 'unsplash', 'pexels'")
    source_url = models.URLField(blank=True, default="")
    attribution = models.TextField(blank=True, default="")

    # Processing
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.COMPLETED,
    )
    processed_variants = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dict of platform-specific processed versions: {'instagram': {'file': 'path', 'width': 1080}}",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "media_library_media_asset"
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename

    @property
    def is_image(self):
        return self.media_type == self.MediaType.IMAGE

    @property
    def is_video(self):
        return self.media_type == self.MediaType.VIDEO

    @property
    def aspect_ratio(self):
        if self.width and self.height:
            return round(self.width / self.height, 2)
        return None

    @property
    def file_size_display(self):
        """Human-readable file size."""
        size = self.file_size
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
