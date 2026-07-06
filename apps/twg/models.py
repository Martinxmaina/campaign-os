"""TWG meeting ingest — one row per inbound ``minutes.published`` webhook.

The row is persisted BEFORE any processing so a transient failure (or a deploy
restart) never silently drops a meeting: the raw event survives and can be
re-processed. ``meeting_id`` (the sender's ``X-WAIIS-Meeting-Id``) is the
idempotency key — a re-delivery of the same meeting is a no-op.
"""

import uuid

from django.db import models


class TwgMeetingEvent(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSING = "processing", "Processing"
        DRAFTED = "drafted", "Drafted"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Sender's stable per-meeting id (X-WAIIS-Meeting-Id) — the dedupe key.
    meeting_id = models.CharField(max_length=255, unique=True)
    event = models.CharField(max_length=64, default="minutes.published")
    payload = models.JSONField(default=dict)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RECEIVED
    )
    error = models.TextField(blank=True, default="")

    # The draft Post bundle produced from this meeting (set once drafted).
    post = models.ForeignKey(
        "composer.Post",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="twg_events",
    )

    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"TWG {self.meeting_id} ({self.status})"
