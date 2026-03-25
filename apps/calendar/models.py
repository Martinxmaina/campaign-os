"""Content Calendar models (F-2.3) — scheduling and time slots."""

import uuid

from django.db import models


class PostingSlot(models.Model):
    """Recurring time slot for a social account.

    Defines default publishing times (e.g., Mon/Wed/Fri at 9 AM)
    used for queue-based scheduling.
    """

    class DayOfWeek(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    social_account = models.ForeignKey(
        "social_accounts.SocialAccount",
        on_delete=models.CASCADE,
        related_name="posting_slots",
    )
    day_of_week = models.IntegerField(choices=DayOfWeek.choices)
    time = models.TimeField(help_text="Posting time (in workspace timezone).")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "calendar_posting_slot"
        ordering = ["day_of_week", "time"]
        unique_together = [("social_account", "day_of_week", "time")]

    def __str__(self):
        return f"{self.get_day_of_week_display()} @ {self.time.strftime('%H:%M')} ({self.social_account})"

    @property
    def day_name(self):
        return self.get_day_of_week_display()
