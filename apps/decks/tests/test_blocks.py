"""Tests for the walled deck Block library (TB.5 Task 1).

A ``Block`` is one pre-approved, single-track, single-audience unit of deck
content (a claim/stat/bio/...). Only ``confirmed`` blocks ever assemble into a
deck; ``block.confirm(by_user)`` is the audited gate that flips the status.
``seed_blocks`` lays down a realistic AfCEN library (idempotently).
"""
import logging

import pytest

from apps.decks.models import Block


@pytest.fixture
def joseph(db, user):
    return user


def _block(owner, **kw):
    defaults = dict(
        type=Block.Type.CLAIM,
        track="ai10bn",
        audience_type=Block.Audience.PHILANTHROPY_ANCHOR,
        sensitivity=Block.Sensitivity.PUBLIC_SAFE,
        confirmation_status=Block.Confirmation.UNCONFIRMED,
        content_md="Africa is the next frontier for catalytic capital.",
        owner=owner,
    )
    defaults.update(kw)
    return Block.objects.create(**defaults)


# -------------------------------------------------------------------------
# persistence + field surface
# -------------------------------------------------------------------------


def test_block_persists_full_field_surface(joseph):
    b = _block(
        joseph,
        type=Block.Type.STAT,
        track="waiis",
        audience_type=Block.Audience.DFI,
        sensitivity=Block.Sensitivity.PARTNER_ONLY,
        confirmation_status=Block.Confirmation.NEEDS_REVIEW,
        content_md="$10bn mobilised across blended-finance vehicles.",
        source_ref="dossier:abc#L2",
        version=2,
    )
    b.refresh_from_db()
    assert b.type == "stat"
    assert b.track == "waiis"
    assert b.audience_type == "dfi"
    assert b.sensitivity == "partner_only"
    assert b.confirmation_status == "needs_review"
    assert b.source_ref == "dossier:abc#L2"
    assert b.owner_id == joseph.id
    assert b.version == 2
    assert b.superseded_by is None


def test_block_type_choices_cover_the_ten_kinds():
    expected = {
        "claim", "stat", "bio", "case_study", "precedent", "governance",
        "ask", "pillar_description", "team", "closing",
    }
    assert {v for v, _ in Block.Type.choices} == expected


def test_source_ref_is_nullable(joseph):
    b = _block(joseph, source_ref=None)
    b.refresh_from_db()
    assert b.source_ref is None


def test_track_accepts_a_list_for_multi_track_blocks(joseph):
    """track may be a single string OR a list of tracks (multi-track block)."""
    b = _block(joseph, track=["core", "programs"])
    b.refresh_from_db()
    assert b.track == ["core", "programs"]


def test_superseded_by_is_a_self_fk(joseph):
    old = _block(joseph, version=1)
    new = _block(joseph, version=2)
    old.superseded_by = new
    old.save(update_fields=["superseded_by"])
    old.refresh_from_db()
    assert old.superseded_by_id == new.id


# -------------------------------------------------------------------------
# confirm() — flips status + writes an audit trail
# -------------------------------------------------------------------------


def test_confirm_flips_status_to_confirmed(joseph):
    b = _block(joseph, confirmation_status=Block.Confirmation.UNCONFIRMED)
    b.confirm(by_user=joseph)
    b.refresh_from_db()
    assert b.confirmation_status == "confirmed"


def test_confirm_writes_an_audit_trail(joseph, caplog):
    b = _block(joseph)
    with caplog.at_level(logging.INFO, logger="apps.decks"):
        b.confirm(by_user=joseph)
    # The audit line names the block + the confirming user.
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert str(b.id) in joined
    assert str(joseph.id) in joined or joseph.email in joined
    assert "confirm" in joined.lower()


# -------------------------------------------------------------------------
# seed_blocks — realistic AfCEN library, idempotent
# -------------------------------------------------------------------------


def test_seed_blocks_creates_a_realistic_afcen_library(joseph):
    from django.core.management import call_command

    call_command("seed_blocks")
    contents = " ".join(Block.objects.values_list("content_md", flat=True))
    # The named AfCEN anchors from the plan are present.
    assert "Mission 300" in contents
    assert "catalytic capital" in contents.lower()  # Rockefeller
    assert "energy-compute" in contents.lower()  # GEAPP
    assert "digital public infrastructure" in contents.lower()  # GIZ


def test_seed_blocks_se4all_stat_is_unconfirmed(joseph):
    from django.core.management import call_command

    call_command("seed_blocks")
    se4all = Block.objects.filter(type=Block.Type.STAT, content_md__icontains="SE4ALL")
    assert se4all.exists()
    assert se4all.first().confirmation_status == "unconfirmed"


def test_seed_blocks_is_idempotent(joseph):
    from django.core.management import call_command

    call_command("seed_blocks")
    first = Block.objects.count()
    assert first > 0
    call_command("seed_blocks")
    assert Block.objects.count() == first
