"""Core outreach-engine models — the deliverability spine.

``Mailbox`` is a per-owner Gmail sending identity (its live transport is a
member's ``joseph.GoogleIntegration``); it carries a daily cap and a warm-up
ramp. ``MailboxSend`` is the per-day send counter (one row per mailbox per day,
incremented by the guarded sender). ``SuppressionEntry`` is an opted-out /
bounced address that must never be sent to. The gate stays authoritative on
every outbound email; these models only enforce cap/ramp/suppression.
"""
import uuid

from django.conf import settings
from django.db import models


class TimestampedUUID(models.Model):
    """UUID pk + created/updated timestamps (mirrors apps.crm.TimestampedUUID)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# Fixed warm-up ramp: week 0 → 20/day, week 1 → 35/day, week 2+ → daily_cap.
RAMP_CAPS = [20, 35]


class Mailbox(TimestampedUUID):
    """A per-owner Gmail sending identity with a daily cap and warm-up ramp."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        PAUSED = "paused"
        DISABLED = "disabled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        related_name="outreach_mailboxes",
    )
    email = models.EmailField(db_index=True)
    # The live transport: a member's Google OAuth grant (gmail.send). Null until
    # connected; Instantly is a separate stub seam (no FK).
    google_integration = models.ForeignKey(
        "joseph.GoogleIntegration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="outreach_mailboxes",
    )
    daily_cap = models.PositiveIntegerField(default=50)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    ramp_started_at = models.DateTimeField(null=True, blank=True)

    def effective_cap_for(self, week_index):
        """Cap for a given warm-up week: [20, 35] for weeks 0/1, then daily_cap."""
        if week_index < len(RAMP_CAPS):
            return RAMP_CAPS[week_index]
        return self.daily_cap

    def __str__(self):
        return self.email


class MailboxSend(TimestampedUUID):
    """One row per mailbox per calendar day — the cap counter."""

    mailbox = models.ForeignKey(Mailbox, on_delete=models.CASCADE, related_name="sends")
    date = models.DateField(db_index=True)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["mailbox", "date"], name="uniq_mailboxsend_per_day"
            )
        ]

    def __str__(self):
        return f"{self.mailbox_id} {self.date}: {self.count}"


class SuppressionEntry(TimestampedUUID):
    """An address that must never be sent to (unsubscribe / bounce / complaint)."""

    email = models.EmailField(unique=True, db_index=True)
    reason = models.CharField(max_length=32, default="unsubscribe")

    def __str__(self):
        return f"{self.email} ({self.reason})"
