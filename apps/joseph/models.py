"""Models backing Joseph's calendar/inbox feeds.

These are the only Django-side persistent state for the Joseph spine; all the
rest of the surface reads agent-service over HTTP (see apps/joseph/readers.py).

- ``GoogleIntegration`` holds a member's Google OAuth refresh token (encrypted
  at rest) plus the granted scopes, so the Celery sync tasks (Task 10/11) can
  mint short-lived access tokens for Calendar/Gmail. One row per user; the
  feeds no-op gracefully when none exists (safe to deploy before re-consent).
- ``CalendarEvent`` is the workspace-scoped mirror of an upcoming Google
  Calendar event, optionally fuzzy-linked to an agent-service thread
  (``linked_thread_id``). It feeds the Today strip on home and the action
  queue's linkage suggestions when unlinked.
"""
import uuid

from django.conf import settings
from django.db import models

from apps.common.encryption import EncryptedTextField


class GoogleIntegration(models.Model):
    """A member's Google OAuth grant (refresh token + scopes) for the feeds."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_integrations",
    )
    # Stored AES-256-GCM encrypted at rest; decrypts transparently on read.
    refresh_token = EncryptedTextField()
    scopes = models.JSONField(default=list, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "joseph_google_integration"

    def __str__(self):
        return f"GoogleIntegration({self.user_id})"


class CalendarEvent(models.Model):
    """A Google Calendar event mirrored locally, optionally linked to a thread."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="joseph_calendar_events",
    )
    google_event_id = models.CharField(max_length=255, unique=True, db_index=True)
    title = models.CharField(max_length=500, blank=True, default="")
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    attendees = models.JSONField(default=list, blank=True)
    # Empty string = unlinked (surfaces as a linkage suggestion in the queue).
    linked_thread_id = models.CharField(max_length=64, blank=True, default="")
    briefing_status = models.CharField(max_length=20, default="none")
    raw = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "joseph_calendar_event"
        ordering = ["start"]

    def __str__(self):
        return f"{self.title} @ {self.start:%Y-%m-%d %H:%M}"
