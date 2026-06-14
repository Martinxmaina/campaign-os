import uuid

from django.conf import settings
from django.db import models


class TimestampedUUID(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Organization(TimestampedUUID):
    class Type(models.TextChoices):
        FUNDER = "funder"
        BILATERAL = "bilateral"
        DFI = "dfi"
        CORPORATE = "corporate"
        PARTNER = "partner"
        GOVERNMENT = "government"

    class Tier(models.TextChoices):
        T1 = "tier1_anchor", "Tier 1 / Anchor"
        T2 = "tier2_warm", "Tier 2 / Warm"
        T3 = "tier3_cold", "Tier 3 / Cold"

    name = models.CharField(max_length=255, db_index=True)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.FUNDER)
    track_tags = models.JSONField(default=list, blank=True)  # ["core","ai10bn","waiis","programs"]
    tier = models.CharField(max_length=16, choices=Tier.choices, blank=True, default="")
    website = models.URLField(blank=True, default="")
    linkedin_url = models.URLField(blank=True, default="")
    wiki_slug = models.CharField(max_length=160, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    def __str__(self):
        return self.name


class Contact(TimestampedUUID):
    class Seniority(models.TextChoices):
        C = "c_suite", "C-suite"
        VP = "vp"
        DIR = "director"
        MGR = "manager"
        AN = "analyst"

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="contacts")
    full_name = models.CharField(max_length=255, db_index=True)
    role = models.CharField(max_length=255, blank=True, default="")
    seniority = models.CharField(max_length=16, choices=Seniority.choices, blank=True, default="")
    email = models.EmailField(blank=True, default="", db_index=True)
    linkedin_url = models.URLField(blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    warmth_source = models.CharField(max_length=32, blank=True, default="")  # direct_relationship|warm_intro|conference|cold
    consent_flags = models.JSONField(default=dict, blank=True)
    last_verified = models.DateField(null=True, blank=True)
    wiki_slug = models.CharField(max_length=160, blank=True, default="")

    def __str__(self):
        return self.full_name


class OutreachThread(TimestampedUUID):
    class Stage(models.TextChoices):
        TARGETED = "targeted"
        ENGAGED = "engaged"
        PROPOSAL = "proposal_sent"
        DISCUSSION = "in_discussion"
        COMMITTED = "committed"
        CONTRACTED = "contracted"
        CLOSED = "closed"

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="threads")
    primary_contact = models.ForeignKey(
        Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name="threads"
    )
    track = models.CharField(max_length=32, blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="owned_threads"
    )
    backstop = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backstop_threads",
    )
    stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.TARGETED)
    warmth = models.CharField(max_length=8, blank=True, default="")  # cold|warm|hot
    score = models.FloatField(default=0.0)
    quintile = models.IntegerField(default=0)
    next_action = models.TextField(blank=True, default="")
    next_action_due = models.DateField(null=True, blank=True)
    traffic_light = models.CharField(max_length=8, default="green")  # green|amber|red
    dossier_id = models.CharField(max_length=64, blank=True, default="")  # agent-service Dossier UUID
    data_room_url = models.URLField(blank=True, default="")
    restricted = models.BooleanField(default=False)
    sector = models.CharField(max_length=32, blank=True, default="")
    pillar = models.CharField(max_length=48, blank=True, default="")
    last_touch = models.DateTimeField(null=True, blank=True)
    last_touch_channel = models.CharField(max_length=32, blank=True, default="")
    agent_thread_id = models.CharField(max_length=64, blank=True, default="", db_index=True)  # source id from migration

    def __str__(self):
        return f"{self.org.name} · {self.stage}"


class Activity(TimestampedUUID):
    thread = models.ForeignKey(OutreachThread, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=32)  # email_sent|email_reply|call|meeting|note|stage_advanced|...
    actor_type = models.CharField(max_length=8, default="human")  # human|agent
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    agent_name = models.CharField(max_length=48, blank=True, default="")
    content_ref = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]


class CrmImportJob(TimestampedUUID):
    """A single run of the 4-step CRM import wizard (upload → map → preview → commit).

    Holds the source (file or Google Sheet), the chosen header→CRM-field
    mapping, a status as the wizard advances, and the per-row commit results
    (so a failed row is reported, never silently dropped).
    """

    class Source(models.TextChoices):
        FILE = "file"
        SHEET = "sheet"

    class Status(models.TextChoices):
        UPLOADED = "uploaded"
        MAPPED = "mapped"
        PREVIEWED = "previewed"
        COMMITTED = "committed"
        FAILED = "failed"

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="crm_import_jobs"
    )
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.FILE)
    filename = models.CharField(max_length=255, blank=True, default="")
    sheet_url = models.URLField(blank=True, default="")
    mapping = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPLOADED)
    results = models.JSONField(default=list, blank=True)
    row_count = models.IntegerField(default=0)

    def __str__(self):
        return f"CrmImportJob {self.id} ({self.source}/{self.status})"


class Task(TimestampedUUID):
    class Status(models.TextChoices):
        OPEN = "open"
        DONE = "completed"
        DISMISSED = "dismissed"

    thread = models.ForeignKey(
        OutreachThread, on_delete=models.CASCADE, null=True, blank=True, related_name="tasks"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crm_tasks"
    )
    type = models.CharField(max_length=32)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    due = models.DateField(null=True, blank=True)
    drafted_content = models.TextField(blank=True, default="")
    gate_id = models.CharField(max_length=64, blank=True, default="")
