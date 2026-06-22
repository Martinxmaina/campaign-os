"""Deck module models (TB.5).

The ``Block`` is the atom of the *walled* deck library: one pre-approved,
single-track, single-audience unit of content (a claim/stat/bio/...). The wall
is enforced downstream at assembly time, but the block carries everything the
wall checks — its track(s), audience type, sensitivity and confirmation status.

Only ``confirmed`` blocks ever assemble into a deck. ``block.confirm(by_user)``
is the single audited entry point that flips a block to ``confirmed`` and writes
an audit line naming the block + the confirming user, so the provenance of every
slide is traceable back to a human decision.
"""
import logging
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

logger = logging.getLogger("apps.decks")


class Block(models.Model):
    """One pre-approved unit of deck content in the walled library."""

    class Type(models.TextChoices):
        CLAIM = "claim"
        STAT = "stat"
        BIO = "bio"
        CASE_STUDY = "case_study"
        PRECEDENT = "precedent"
        GOVERNANCE = "governance"
        ASK = "ask"
        PILLAR_DESCRIPTION = "pillar_description"
        TEAM = "team"
        CLOSING = "closing"

    class Audience(models.TextChoices):
        PHILANTHROPY_ANCHOR = "philanthropy_anchor"
        BILATERAL_TA = "bilateral_ta"
        CORPORATE_SPONSOR = "corporate_sponsor"
        DFI = "dfi"
        INTERNAL = "internal"

    class Sensitivity(models.TextChoices):
        PUBLIC_SAFE = "public_safe"
        PARTNER_ONLY = "partner_only"
        CONFIDENTIAL = "confidential"

    class Confirmation(models.TextChoices):
        CONFIRMED = "confirmed"
        UNCONFIRMED = "unconfirmed"
        NEEDS_REVIEW = "needs_review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=24, choices=Type.choices, db_index=True)
    # A single track string ("core"|"programs"|"waiis"|"ai10bn") OR a list of
    # tracks for a multi-track block — kept as JSON so both shapes round-trip.
    track = models.JSONField(default=str, blank=True)
    audience_type = models.CharField(max_length=24, choices=Audience.choices, db_index=True)
    sensitivity = models.CharField(
        max_length=16, choices=Sensitivity.choices, default=Sensitivity.PUBLIC_SAFE
    )
    confirmation_status = models.CharField(
        max_length=16, choices=Confirmation.choices, default=Confirmation.UNCONFIRMED, db_index=True
    )
    content_md = models.TextField(blank=True, default="")
    # A dossier/wiki/source citation (e.g. "dossier:<id>#L2"); nullable when the
    # block is self-evident or its provenance is the source_ref of its parent.
    source_ref = models.CharField(max_length=255, null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deck_blocks"
    )
    version = models.IntegerField(default=1)
    superseded_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supersedes",
    )
    # Stable de-dup key so seed_blocks (and future supersede chains) stay idempotent.
    seed_key = models.CharField(max_length=120, blank=True, default="", db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "decks_block"
        ordering = ["type", "-version"]

    def __str__(self):
        return f"Block({self.type}, v{self.version})"

    @property
    def tracks(self) -> list[str]:
        """The block's track(s) normalised to a list (single string -> [string])."""
        if isinstance(self.track, list):
            return [t for t in self.track if t]
        return [self.track] if self.track else []

    def confirm(self, by_user) -> "Block":
        """Flip the block to ``confirmed`` and write an audit trail.

        This is the only sanctioned path to ``confirmed`` — assembly trusts the
        status, so every confirmation must be an auditable human decision.
        """
        self.confirmation_status = self.Confirmation.CONFIRMED
        self.save(update_fields=["confirmation_status", "updated_at"])
        logger.info(
            "deck block confirmed: block=%s type=%s by_user=%s (%s) at=%s",
            self.id,
            self.type,
            getattr(by_user, "id", None),
            getattr(by_user, "email", ""),
            timezone.now().isoformat(),
        )
        return self


class DeckRegistry(models.Model):
    """One assembled deck for a thread — the durable record of an assembly run.

    The registry is the *source of truth* for what a deck contains: the exact
    block **versions** that were assembled (so continuity in Task 4 and the
    stale-figure report in Task 3 can diff a sent deck against the live library),
    the gate verdict that cleared (or flagged) the generated personalization, and
    the placeholder Slides handle from the render SEAM. A flagged gate marks the
    deck un-sendable (``is_sendable``) but never un-reviewable — Joseph can always
    open a draft deck to inspect/fix the finding.
    """

    class Status(models.TextChoices):
        DRAFT = "draft"
        SENT = "sent"
        ARCHIVED = "archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(
        "crm.OutreachThread", on_delete=models.CASCADE, related_name="decks"
    )
    skeleton_id = models.CharField(max_length=48, db_index=True)
    # {slot_or_type: [block_id, ...]} — the exact block versions assembled, so a
    # later library change is detectable (block.superseded_by) per deck.
    block_versions = models.JSONField(default=dict, blank=True)
    # The structured per-slide payload the render SEAM (and the review screen)
    # consume: [{slide, type, block_ids, content_md, personalization, citations}].
    slides_payload = models.JSONField(default=list, blank=True)
    presenter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="presented_decks"
    )
    ask_amount = models.CharField(max_length=64, blank=True, default="")
    # The thread stage at assembly time — so a later deck can detect a stage
    # advance for the continuity ask-slide update + change summary (Task 4).
    thread_stage = models.CharField(max_length=24, blank=True, default="")
    # The dossier ``updated_at`` snapshot at assembly time — so a later deck can
    # note dossier-diff funder updates in the change summary (Task 4).
    dossier_updated_at = models.CharField(max_length=64, blank=True, default="")
    gate_id = models.CharField(max_length=64, blank=True, default="")
    # The gate findings on the generated personalization (empty == clean). A
    # non-empty findings list marks the deck un-sendable (see ``is_sendable``).
    findings = models.JSONField(default=list, blank=True)
    slides_url = models.URLField(blank=True, default="")  # placeholder until live Slides
    slides_id = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    # Continuity (Task 4): when this deck is a *follow-up* to a prior SENT deck for
    # the same thread, ``is_continuation`` is True and ``change_summary`` carries
    # the "what changed" delta ({dropped, new, stage_advanced, dossier_updated}).
    is_continuation = models.BooleanField(default=False)
    change_summary = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "decks_registry"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["thread", "-created_at"])]

    def __str__(self):
        return f"Deck({self.skeleton_id}, {self.status})"

    @property
    def is_sendable(self) -> bool:
        """A deck is sendable only when the gate cleared with zero findings.

        Findings never block *review* (Joseph can always open the draft) — they
        block *send*, mirroring the publish/outreach gate invariant.
        """
        return not self.findings


class DeckVersion(models.Model):
    """An immutable snapshot of a deck at one assembly/edit cycle.

    Every change to a deck — the initial assembly, an edit, a revert — appends a
    ``DeckVersion`` (the ``block_versions`` map + the ``slides_payload`` at that
    moment + the gate verdict). The review screen's version-history rail reads
    these; ``revert`` restores one by writing a NEW row (never mutating an old
    snapshot), so the full lineage is always recoverable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deck = models.ForeignKey(
        DeckRegistry, on_delete=models.CASCADE, related_name="versions"
    )
    # Monotonic per-deck sequence (1, 2, 3, …) for the history rail + revert UI.
    number = models.PositiveIntegerField(default=1)
    block_versions = models.JSONField(default=dict, blank=True)
    slides_payload = models.JSONField(default=list, blank=True)
    gate_id = models.CharField(max_length=64, blank=True, default="")
    findings = models.JSONField(default=list, blank=True)
    # Why this version exists: "assembled" | "edited" | "revert to v<N>" | …
    reason = models.CharField(max_length=120, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deck_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "decks_version"
        ordering = ["deck", "number"]
        unique_together = [("deck", "number")]

    def __str__(self):
        return f"DeckVersion({self.deck_id}, v{self.number})"


def record_version(deck: DeckRegistry, *, reason: str = "", created_by=None) -> DeckVersion:
    """Append a ``DeckVersion`` snapshotting ``deck``'s current live state.

    The single sanctioned path to a new version row — assembly, edits and revert
    all funnel through here, so the per-deck ``number`` sequence stays gap-free
    and every snapshot carries the live ``block_versions`` + ``slides_payload`` +
    gate verdict at that moment.
    """
    last = deck.versions.order_by("-number").first()
    number = (last.number + 1) if last else 1
    return DeckVersion.objects.create(
        deck=deck,
        number=number,
        block_versions=deck.block_versions,
        slides_payload=deck.slides_payload,
        gate_id=deck.gate_id,
        findings=deck.findings,
        reason=reason,
        created_by=created_by,
    )
