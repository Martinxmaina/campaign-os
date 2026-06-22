"""Tests for deck continuity (TB.5 Task 4).

Assembling a *second* deck for a thread that already has a **sent** deck is not a
fresh assembly — it is a *delta*:

  - slides whose blocks were all in the previous (sent) deck are dropped, and the
    deck carries a "what changed" summary (the dropped + the new slide lists);
  - a generated "Progress since <date>" slide is inserted, populated from the
    ``Activity`` rows (commitments / meetings / milestones) booked since the last
    deck — Joseph reviews it (status draft);
  - the ask slide is updated when the thread ``stage`` advanced since the last
    deck;
  - dossier-diff funder updates are noted on the change summary.

The first deck for a thread is unaffected (no prior sent deck → no continuity).
The dossier readers + gate + voice are mocked/SEAMed (no network).
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.crm.models import Activity, Organization, OutreachThread
from apps.decks.models import Block, DeckRegistry

PASS_GATE = {"verdict": "pass", "findings": [], "gate_id": "g-pass", "content_hash": "h1"}

DOSSIER = {
    "body_md": "Rockefeller is the catalytic-capital anchor for the AI decade.",
    "hooks": {"ai10bn": "Africa will not be a footnote in the AI decade."},
    "hook_by_track": {"ai10bn": "Africa will not be a footnote in the AI decade."},
    "sources": [{"id": "src-1", "title": "Mission 300 brief", "url": "https://x"}],
    "updated_at": "2026-06-01T00:00:00Z",
}


@pytest.fixture
def joseph(db, user):
    return user


@pytest.fixture
def thread(db):
    org = Organization.objects.create(name="Rockefeller Foundation", type=Organization.Type.FUNDER)
    return OutreachThread.objects.create(org=org, track="ai10bn", restricted=False)


def _block(owner, **kw):
    defaults = dict(
        type=Block.Type.CLAIM,
        track="ai10bn",
        audience_type=Block.Audience.PHILANTHROPY_ANCHOR,
        sensitivity=Block.Sensitivity.PUBLIC_SAFE,
        confirmation_status=Block.Confirmation.CONFIRMED,
        content_md="Mission 300 connects 300m Africans to power.",
        source_ref="wiki:mission-300",
        owner=owner,
    )
    defaults.update(kw)
    return Block.objects.create(**defaults)


def _anchor_library(owner):
    return {
        "claim": _block(owner, type=Block.Type.CLAIM, content_md="Mission 300.", source_ref="wiki:m300"),
        "pillar": _block(
            owner, type=Block.Type.PILLAR_DESCRIPTION, content_md="Catalytic capital.", source_ref="wiki:cc"
        ),
        "stat": _block(owner, type=Block.Type.STAT, content_md="$10bn mobilised.", source_ref="wiki:10bn"),
        "ask": _block(owner, type=Block.Type.ASK, content_md="Anchor the round.", source_ref="wiki:ask"),
    }


def _patched(dossier=None, gate=PASS_GATE):
    dossier = DOSSIER if dossier is None else dossier
    return (
        patch("apps.decks.assembly.get_dossier", return_value=dossier),
        patch("apps.decks.assembly.compile_dossier", return_value=dossier),
        patch("apps.decks.assembly.apply_voice", side_effect=lambda t: t),
        patch("apps.decks.assembly.check_gate", return_value=gate),
        patch("apps.decks.assembly.notify"),
    )


def _assemble(thread, joseph, **kw):
    from apps.decks.assembly import assemble_deck

    p_get, p_compile, p_voice, p_gate, p_notify = _patched(dossier=kw.pop("dossier", None))
    with p_get, p_compile, p_voice, p_gate, p_notify:
        return assemble_deck(thread, "philanthropy_anchor", presenter=joseph, **kw)


# -------------------------------------------------------------------------
# first deck: no continuity (nothing to diff against)
# -------------------------------------------------------------------------


def test_first_deck_has_no_change_summary(joseph, thread):
    _anchor_library(joseph)
    deck = _assemble(thread, joseph)
    # No prior sent deck → not a continuity assembly.
    assert deck.is_continuation is False
    assert not deck.change_summary


def test_only_a_SENT_prior_deck_triggers_continuity(joseph, thread):
    """A prior *draft* deck is not yet "out there" — it must not trigger continuity."""
    _anchor_library(joseph)
    first = _assemble(thread, joseph)  # status draft, never sent
    assert first.status == DeckRegistry.Status.DRAFT
    second = _assemble(thread, joseph)
    assert second.is_continuation is False


# -------------------------------------------------------------------------
# second deck (prior SENT): drop repeated slides + "what changed" summary
# -------------------------------------------------------------------------


def test_second_deck_drops_slides_whose_blocks_were_in_prior_sent_deck(joseph, thread):
    _anchor_library(joseph)
    first = _assemble(thread, joseph)
    first.status = DeckRegistry.Status.SENT
    first.save(update_fields=["status"])

    second = _assemble(thread, joseph)
    assert second.is_continuation is True
    # Every content slide repeats the prior deck's blocks → they are dropped; the
    # change summary lists what was dropped and what is new.
    assert "dropped" in second.change_summary
    assert "new" in second.change_summary
    assert second.change_summary["dropped"]  # at least one repeated slide dropped
    # A dropped slide's blocks are not re-shown verbatim in the new content slides.
    surviving = [s for s in second.slides_payload if s.get("block_ids")]
    prior_block_ids = {b for ids in first.block_versions.values() for b in ids}
    for s in surviving:
        # any surviving content slide is the progress slide, the (always-restated)
        # ask slide, or carries a block not in the prior deck.
        is_ask = "ask" in (s.get("accepted_block_types") or [])
        assert (
            s.get("kind") == "progress"
            or is_ask
            or any(b not in prior_block_ids for b in s["block_ids"])
        )


# -------------------------------------------------------------------------
# "Progress since <date>" slide from Activity rows
# -------------------------------------------------------------------------


def test_progress_slide_inserted_from_activities_since_last_deck(joseph, thread):
    _anchor_library(joseph)
    first = _assemble(thread, joseph)
    first.status = DeckRegistry.Status.SENT
    first.save(update_fields=["status"])

    # Activities booked AFTER the first deck went out.
    Activity.objects.create(
        thread=thread, activity_type="meeting", content_ref={"summary": "Kickoff call with the program team"}
    )
    Activity.objects.create(
        thread=thread,
        activity_type="commitment_recorded",
        content_ref={"summary": "Verbal interest in anchoring $25m"},
    )

    second = _assemble(thread, joseph)
    progress = [s for s in second.slides_payload if s.get("kind") == "progress"]
    assert len(progress) == 1
    slide = progress[0]
    assert "Progress since" in slide["title"]
    body = (slide.get("content_md", "") + " " + " ".join(slide.get("items", []))).lower()
    assert "kickoff" in body or "meeting" in body
    assert "anchor" in body or "commitment" in body
    # Joseph reviews it — the whole deck is a draft.
    assert second.status == DeckRegistry.Status.DRAFT


def test_progress_slide_only_counts_activities_after_last_deck(joseph, thread):
    _anchor_library(joseph)
    # An OLD activity, before the first deck.
    old = Activity.objects.create(
        thread=thread, activity_type="note", content_ref={"summary": "OLD pre-deck note"}
    )
    Activity.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))

    first = _assemble(thread, joseph)
    first.status = DeckRegistry.Status.SENT
    first.save(update_fields=["status"])

    Activity.objects.create(
        thread=thread, activity_type="meeting", content_ref={"summary": "NEW post-deck meeting"}
    )
    second = _assemble(thread, joseph)
    progress = [s for s in second.slides_payload if s.get("kind") == "progress"]
    assert progress
    body = (progress[0].get("content_md", "") + " " + " ".join(progress[0].get("items", []))).lower()
    assert "new post-deck" in body
    assert "old pre-deck" not in body


# -------------------------------------------------------------------------
# ask slide updated when the thread stage advanced
# -------------------------------------------------------------------------


def test_ask_slide_updated_when_stage_advanced(joseph, thread):
    _anchor_library(joseph)
    thread.stage = OutreachThread.Stage.ENGAGED
    thread.save(update_fields=["stage"])
    first = _assemble(thread, joseph, ask_amount="$10m")
    first.status = DeckRegistry.Status.SENT
    first.save(update_fields=["status"])

    # Stage advances + the ask grows.
    thread.stage = OutreachThread.Stage.PROPOSAL
    thread.save(update_fields=["stage"])
    second = _assemble(thread, joseph, ask_amount="$25m")

    ask_slides = [s for s in second.slides_payload if "ask" in (s.get("accepted_block_types") or [])]
    assert ask_slides
    blob = " ".join(s.get("personalization", "") for s in ask_slides)
    assert "$25m" in blob
    # the change summary records the stage advance
    assert second.change_summary.get("stage_advanced")


# -------------------------------------------------------------------------
# dossier-diff funder updates noted
# -------------------------------------------------------------------------


def test_dossier_diff_funder_updates_noted(joseph, thread):
    _anchor_library(joseph)
    first = _assemble(thread, joseph, dossier=DOSSIER)
    first.status = DeckRegistry.Status.SENT
    first.save(update_fields=["status"])

    # A newer dossier (different updated_at) → continuity notes a funder update.
    newer = dict(DOSSIER, updated_at="2026-06-20T00:00:00Z")
    second = _assemble(thread, joseph, dossier=newer)
    assert second.change_summary.get("dossier_updated")
