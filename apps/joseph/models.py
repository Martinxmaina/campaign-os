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
    # Pre-meeting cascade state machine: none → linked → briefed → captured.
    briefing_status = models.CharField(max_length=20, default="none")
    # Gate-checked talking points drafted by the T-2 cascade stage (Task 2).
    talking_points = models.JSONField(default=list, blank=True)
    # Cascade stages already fired for this event (e.g. ["t5", "t2"]) — the
    # idempotency ledger so a re-run of the beat doesn't double-fire a stage.
    prep_stages = models.JSONField(default=list, blank=True)
    # Post-meeting capture state: none → prompted → captured (or deferred).
    capture_status = models.CharField(max_length=20, default="none")
    # When a capture is deferred, the time to re-prompt (Task 4).
    defer_until = models.DateTimeField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "joseph_calendar_event"
        ordering = ["start"]

    def __str__(self):
        return f"{self.title} @ {self.start:%Y-%m-%d %H:%M}"


class VoiceNote(models.Model):
    """An uploaded meeting recording walking the transcription status machine.

    The ``file`` uses the project's configured default storage (S3Boto3Storage =
    Railway R2 in prod when the ``S3_*`` env is present, FileSystemStorage in
    dev/test) -- no bespoke upload code. The async pipeline (Task 5) moves it
    ``uploaded -> transcribing -> transcribed -> extracted`` (or ``failed``),
    writing the ``transcript`` and producing an ``ExtractedMeeting``.
    """

    class Status(models.TextChoices):
        UPLOADED = "uploaded"
        TRANSCRIBING = "transcribing"
        TRANSCRIBED = "transcribed"
        EXTRACTED = "extracted"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(
        "crm.OutreachThread", on_delete=models.CASCADE, related_name="voice_notes"
    )
    # Optional: the meeting this note captures (the post-meeting capture seam).
    calendar_event = models.ForeignKey(
        CalendarEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="voice_notes",
    )
    file = models.FileField(upload_to="joseph/voice_notes/%Y/%m/")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)
    transcript = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="joseph_voice_notes"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "joseph_voice_note"
        ordering = ["-created_at"]

    def __str__(self):
        return f"VoiceNote({self.thread_id}, {self.status})"


class ExtractedMeeting(models.Model):
    """The structured outcome of one captured meeting (voice note or quick form).

    Holds the transcript, an optional warmth signal and free-text relationship
    notes; its ``ExtractedItem`` children are the accept/edit/dismiss lines the
    confirm screen (Task 6) routes into Activities/Tasks/intake/wiki/warmth.
    Stays ``pending`` until the principal confirms it.
    """

    class Source(models.TextChoices):
        VOICE = "voice"
        FORM = "form"

    class WarmthDelta(models.TextChoices):
        WARMER = "warmer"
        SAME = "same"
        COOLER = "cooler"

    class Status(models.TextChoices):
        PENDING = "pending"
        CONFIRMED = "confirmed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(
        "crm.OutreachThread", on_delete=models.CASCADE, related_name="extracted_meetings"
    )
    voice_note = models.ForeignKey(
        VoiceNote,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extracted_meetings",
    )
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.VOICE)
    transcript = models.TextField(blank=True, default="")
    # Empty string = no warmth signal yet (nullable in spirit; "" is the unset value).
    warmth_delta = models.CharField(
        max_length=8, choices=WarmthDelta.choices, blank=True, default=""
    )
    relationship_notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "joseph_extracted_meeting"
        ordering = ["-created_at"]

    def __str__(self):
        return f"ExtractedMeeting({self.thread_id}, {self.status})"


class ExtractedItem(models.Model):
    """One accept/edit/dismiss line of an ExtractedMeeting.

    ``kind`` is drawn from the routing set the confirm screen dispatches on:
    ``commitment_*`` -> Activity(commitment_recorded) + a confirm-commitment Task;
    interest/objection/strategy -> Activity(note); ``next_step`` -> Task;
    ``intelligence_signal`` (+ wiki_update_candidate) -> WikiRevisionCandidate;
    ``content_idea`` -> ContentIntake.
    """

    class Kind(models.TextChoices):
        COMMITMENT_FINANCIAL = "commitment_financial"
        COMMITMENT_INTRO = "commitment_intro"
        COMMITMENT_FOLLOW_UP = "commitment_follow_up"
        INTEREST_EXPRESSED = "interest_expressed"
        OBJECTION_RAISED = "objection_raised"
        STRATEGY_SIGNAL = "strategy_signal"
        INTELLIGENCE_SIGNAL = "intelligence_signal"
        NEXT_STEP = "next_step"
        CONTENT_IDEA = "content_idea"

    class State(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        EDITED = "edited"
        DISMISSED = "dismissed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(
        ExtractedMeeting, on_delete=models.CASCADE, related_name="items"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    description = models.TextField(blank=True, default="")
    confidence = models.FloatField(default=0.0)
    verbatim_quote = models.TextField(blank=True, default="")
    proposed_due = models.DateField(null=True, blank=True)
    proposed_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposed_meeting_items",
    )
    wiki_update_candidate = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "joseph_extracted_item"
        ordering = ["created_at"]

    def __str__(self):
        return f"ExtractedItem({self.kind}, {self.state})"


class WikiRevisionCandidate(models.Model):
    """A *proposed* wiki edit surfaced from a meeting -- never auto-applied.

    An intelligence signal flagged as a wiki update lands here ``proposed`` and
    waits for human review (Task 6 routing); only an explicit action moves it to
    ``applied`` or ``dismissed``.
    """

    class Status(models.TextChoices):
        PROPOSED = "proposed"
        APPLIED = "applied"
        DISMISSED = "dismissed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "crm.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="wiki_revision_candidates",
    )
    thread = models.ForeignKey(
        "crm.OutreachThread",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="wiki_revision_candidates",
    )
    source_meeting = models.ForeignKey(
        ExtractedMeeting,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="wiki_revision_candidates",
    )
    signal = models.TextField(blank=True, default="")
    proposed_change = models.TextField(blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROPOSED)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "joseph_wiki_revision_candidate"
        ordering = ["-created_at"]

    def __str__(self):
        return f"WikiRevisionCandidate({self.org_id}, {self.status})"
