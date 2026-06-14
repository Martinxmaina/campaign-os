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


# Step ``kind`` values that are *human* channels — never auto-sent. ``advance``
# turns a due human step into a ``crm.Task`` for the thread owner. Everything
# else (``email``) flows through the gated ``send_email`` orchestrator.
HUMAN_CHANNELS = ("linkedin", "whatsapp", "call")


class SequenceTemplate(TimestampedUUID):
    """A reusable multi-step outreach plan.

    ``steps`` is an ordered list of dicts, each
    ``{"kind": "email"|"linkedin"|"whatsapp"|"call", "delay_days": int,
    "subject": str, "body": str}``. ``enroll`` materialises a :class:`Sequence`
    per thread from this plan, computing ``scheduled_for`` as the running sum of
    ``delay_days``.
    """

    name = models.CharField(max_length=120, db_index=True)
    description = models.TextField(blank=True, default="")
    steps = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.name


class Sequence(TimestampedUUID):
    """A template enrolled against one thread — its live, advancing instance."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        PAUSED = "paused"
        COMPLETED = "completed"

    template = models.ForeignKey(
        SequenceTemplate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sequences",
    )
    thread = models.ForeignKey(
        "crm.OutreachThread", on_delete=models.CASCADE, related_name="sequences"
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    def __str__(self):
        return f"Sequence {self.id} ({self.status})"


class SequenceStep(TimestampedUUID):
    """One materialised step of a :class:`Sequence` — email or human-channel."""

    class Status(models.TextChoices):
        PENDING = "pending"
        SENT = "sent"
        TASK_OPEN = "task_open"
        SKIPPED = "skipped"

    sequence = models.ForeignKey(
        Sequence, on_delete=models.CASCADE, related_name="steps"
    )
    position = models.PositiveIntegerField(default=1)
    kind = models.CharField(max_length=16, default="email")
    subject = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField(blank=True, default="")
    delay_days = models.PositiveIntegerField(default=0)
    scheduled_for = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    # Provider message id (email) once sent — audit trail back to the transport.
    message_id = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        ordering = ["position"]

    @property
    def is_human_channel(self) -> bool:
        return self.kind in HUMAN_CHANNELS

    def __str__(self):
        return f"step {self.position} {self.kind} ({self.status})"
