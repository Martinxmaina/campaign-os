"""Content Intake models.

Models:
    ContentIntake   — a single row from the Google Sheets content-planning register,
                      normalised and enriched.
    UnblockCondition — a gating condition that must be resolved before a ContentIntake
                       item may be scheduled/published.
    IntakeReviewItem — a row that failed normalisation and has been quarantined for
                       manual review.
"""

import uuid

from django.conf import settings
from django.db import models

from apps.common.managers import WorkspaceScopedManager


class ContentIntake(models.Model):
    """A single content intake record imported from the planning register."""

    class ProofStatus(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        TBD = "tbd", "TBD"
        NEEDS_VERIFICATION = "needs_verification", "Needs Verification"

    class Sensitivity(models.TextChoices):
        PUBLIC_SAFE = "public_safe", "Public Safe"
        PARTNER_ONLY = "partner_only", "Partner Only"
        PRIVATE_HOLD = "private_hold", "Private Hold"
        CONFIDENTIAL = "confidential", "Confidential"

    class Priority(models.TextChoices):
        HIGH = "H", "High"
        MEDIUM = "M", "Medium"
        LOW = "L", "Low"

    class Status(models.TextChoices):
        IDEA = "idea", "Idea"
        ACCEPTED = "accepted", "Accepted"
        DRAFTING = "drafting", "Drafting"
        IN_REVIEW = "in_review", "In Review"
        APPROVED = "approved", "Approved"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"
        BLOCKED = "blocked", "Blocked"
        HELD = "held", "Held"
        SKIPPED = "skipped", "Skipped"
        REVIEW_QUEUE = "review_queue", "Review Queue"

    # Primary key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Workspace scope
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="content_intakes",
    )

    # Source identity
    external_id = models.CharField(max_length=100)
    row_hash = models.CharField(max_length=64, blank=True, default="")

    # Attribution
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_intakes",
    )
    submitted_by_raw = models.CharField(max_length=255, blank=True, default="")

    # Content metadata
    pillar_theme = models.CharField(max_length=255, blank=True, default="")
    angle = models.CharField(max_length=255, blank=True, default="")
    proof_point = models.TextField(blank=True, default="")
    proof_status = models.CharField(
        max_length=20,
        choices=ProofStatus.choices,
        default=ProofStatus.TBD,
    )
    target_audience = models.CharField(max_length=255, blank=True, default="")
    sensitivity = models.CharField(
        max_length=20,
        choices=Sensitivity.choices,
        default=Sensitivity.PRIVATE_HOLD,
    )
    channel_targets = models.JSONField(default=list, blank=True)
    campaign = models.CharField(max_length=255, blank=True, default="")
    house = models.CharField(max_length=100, blank=True, default="")
    priority = models.CharField(
        max_length=1,
        choices=Priority.choices,
        blank=True,
        default="",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IDEA,
    )

    # Ownership
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_intakes",
    )
    owner_raw = models.CharField(max_length=255, blank=True, default="")

    # Scheduling
    target_publish_date = models.DateField(null=True, blank=True)

    # Supplementary
    notes_raw = models.TextField(blank=True, default="")
    reference_links = models.JSONField(default=list, blank=True)
    skip_reason = models.CharField(max_length=255, blank=True, default="")

    # Sync tracking
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.CharField(max_length=500, blank=True, default="")

    # Linked composer post (set once a draft has been created)
    post = models.OneToOneField(
        "composer.Post",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intake",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "content_intake_contentintake"
        unique_together = [("workspace", "external_id")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.external_id}] {self.pillar_theme} — {self.angle}"

    # ------------------------------------------------------------------
    # Scheduling predicates
    # ------------------------------------------------------------------

    @property
    def has_open_conditions(self) -> bool:
        """True if any UnblockCondition for this item is still open."""
        return self.unblock_conditions.filter(
            status=UnblockCondition.Status.OPEN
        ).exists()

    @property
    def is_schedulable(self) -> bool:
        """False when any hard gate applies; True otherwise.

        Hard gates (fail-closed):
        - sensitivity is private_hold or confidential
        - proof_status is needs_verification
        - at least one open unblock condition exists
        """
        _BLOCKED_SENSITIVITIES = {
            self.Sensitivity.PRIVATE_HOLD,
            self.Sensitivity.CONFIDENTIAL,
        }
        if self.sensitivity in _BLOCKED_SENSITIVITIES:
            return False
        if self.proof_status == self.ProofStatus.NEEDS_VERIFICATION:
            return False
        if self.has_open_conditions:
            return False
        return True


class UnblockCondition(models.Model):
    """A gating condition that blocks scheduling until resolved."""

    class ConditionType(models.TextChoices):
        SOURCE_VERIFICATION = "source_verification", "Source Verification"
        PARTNER_PERMISSION = "partner_permission", "Partner Permission"
        LEGAL_MILESTONE = "legal_milestone", "Legal Milestone"
        FIGURE_CONFIRMATION = "figure_confirmation", "Figure Confirmation"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    intake = models.ForeignKey(
        ContentIntake,
        on_delete=models.CASCADE,
        related_name="unblock_conditions",
    )
    condition_type = models.CharField(
        max_length=30,
        choices=ConditionType.choices,
    )
    description = models.TextField()
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_conditions",
    )
    owner_raw = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
    )
    evidence_note = models.TextField(blank=True, default="")
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_conditions",
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "content_intake_unblockcondition"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.condition_type} — {self.status} ({self.intake.external_id})"


class IntakeReviewItem(models.Model):
    """A row that failed normalisation, quarantined for manual triage."""

    class Reason(models.TextChoices):
        SENSITIVITY_UNRECOGNIZED = "sensitivity_unrecognized", "Sensitivity Unrecognized"
        STATUS_UNMAPPED = "status_unmapped", "Status Unmapped"
        CHANNEL_UNPARSEABLE = "channel_unparseable", "Channel Unparseable"
        GENERAL_PARSE_FAILURE = "general_parse_failure", "General Parse Failure"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="intake_review_items",
    )
    external_id = models.CharField(max_length=100, blank=True, default="")
    raw_row = models.JSONField(default=dict)
    reason = models.CharField(
        max_length=30,
        choices=Reason.choices,
    )
    detail = models.TextField(blank=True, default="")
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_review_items",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "content_intake_intakereviewitem"
        ordering = ["-created_at"]

    def __str__(self):
        return f"ReviewItem {self.external_id or self.id} — {self.reason}"
