"""Tests for the deck assembly engine (TB.5 Task 2).

``assemble_deck(thread, skeleton_id, ask_amount, presenter)`` is the walled
selection + cited personalization + gate-verify + registry pipeline:

  (a) loads the dossier (L2 preferred, L1 fallback, compile then proceed);
  (b) selects blocks by track / audience_type / sensitivity ≤ thread / confirmed;
  (c) cross-track block → ``DeckAssemblyError`` naming the block id (HARD error);
  (d) required slot with no confirmed block → ``DeckAssemblyError`` naming slide+field;
  (e) personalization (hook framing + audience vocabulary + ask) is voiced then
      gated; a finding lands on the registry (un-sendable, still reviewable);
      every generated claim cites a dossier source or a block id else "untraceable";
  (f) a ``DeckRegistry`` row is written and ``notify(...DECK_READY...)`` fires.

The Google Slides render + the voice pass are deterministic SEAMS; the gate +
dossier readers are mocked (no network).
"""
from unittest.mock import patch

import pytest

from apps.crm.models import Organization, OutreachThread
from apps.decks.models import Block, DeckRegistry

PASS_GATE = {"verdict": "pass", "findings": [], "gate_id": "g-pass", "content_hash": "h1"}
FLAG_GATE = {
    "verdict": "flag",
    "findings": [{"rule": "token_language", "match": "guaranteed"}],
    "gate_id": "g-flag",
    "content_hash": "h2",
}

DOSSIER = {
    "body_md": "Rockefeller is the catalytic-capital anchor for the AI decade.",
    "summary": "Anchor philanthropic partner.",
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
    org = Organization.objects.create(name="Rockefeller Foundation")
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
    """A minimally-complete philanthropy_anchor library (every required slot fillable)."""
    return {
        "claim": _block(owner, type=Block.Type.CLAIM, content_md="Mission 300.", source_ref="wiki:m300"),
        "pillar": _block(
            owner, type=Block.Type.PILLAR_DESCRIPTION, content_md="Catalytic capital.", source_ref="wiki:cc"
        ),
        "stat": _block(owner, type=Block.Type.STAT, content_md="$10bn mobilised.", source_ref="wiki:10bn"),
        "ask": _block(owner, type=Block.Type.ASK, content_md="Anchor the round.", source_ref="wiki:ask"),
    }


def _patched(dossier=None, gate=PASS_GATE):
    """Patch the dossier readers + gate seam used by assembly."""
    dossier = DOSSIER if dossier is None else dossier
    return (
        patch("apps.decks.assembly.get_dossier", return_value=dossier),
        patch("apps.decks.assembly.compile_dossier", return_value=dossier),
        patch("apps.decks.assembly.check_gate", return_value=gate),
        patch("apps.decks.assembly.notify"),
    )


# -------------------------------------------------------------------------
# (a) dossier load: L2 preferred, L1 fallback, compile then proceed
# -------------------------------------------------------------------------


def test_assemble_compiles_dossier_when_thread_has_none(joseph, thread):
    from apps.decks.assembly import assemble_deck

    _anchor_library(joseph)
    p_get, p_compile, p_gate, p_notify = _patched(dossier={})
    # thread has no dossier_id → no get_dossier; compile is called, proceed with what we have.
    with p_get as get_d, p_compile as comp, p_gate, p_notify:
        deck = assemble_deck(thread, "philanthropy_anchor", ask_amount="$25m", presenter=joseph)
    comp.assert_called_once()
    assert deck.id is not None


def test_assemble_prefers_existing_dossier_no_compile(joseph, thread):
    from apps.decks.assembly import assemble_deck

    thread.dossier_id = "dos-1"
    thread.save(update_fields=["dossier_id"])
    _anchor_library(joseph)
    p_get, p_compile, p_gate, p_notify = _patched()
    with p_get as get_d, p_compile as comp, p_gate, p_notify:
        assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    get_d.assert_called_once()
    comp.assert_not_called()


# -------------------------------------------------------------------------
# (c) cross-track wall — HARD error naming the offending block id
# -------------------------------------------------------------------------


def test_cross_track_block_raises_naming_block_id(joseph, thread):
    from apps.decks.assembly import DeckAssemblyError, assemble_deck

    _anchor_library(joseph)
    # A philanthropy_anchor claim on the WRONG track (thread is ai10bn).
    rogue = _block(
        joseph, type=Block.Type.CLAIM, track="waiis", content_md="Off-track claim.", version=2
    )
    p_get, p_compile, p_gate, p_notify = _patched()
    with p_get, p_compile, p_gate, p_notify:
        with pytest.raises(DeckAssemblyError) as exc:
            assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    assert str(rogue.id) in str(exc.value)


# -------------------------------------------------------------------------
# (b) selection wall — confirmed-only + sensitivity ≤ thread
# -------------------------------------------------------------------------


def test_only_confirmed_blocks_assemble(joseph, thread):
    from apps.decks.assembly import assemble_deck

    lib = _anchor_library(joseph)
    # an unconfirmed extra stat must never be selected
    _block(
        joseph,
        type=Block.Type.STAT,
        confirmation_status=Block.Confirmation.UNCONFIRMED,
        content_md="UNCONFIRMED FIGURE.",
        version=2,
    )
    p_get, p_compile, p_gate, p_notify = _patched()
    with p_get, p_compile, p_gate, p_notify:
        deck = assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    selected_ids = {bid for ids in deck.block_versions.values() for bid in ids}
    assert str(lib["stat"].id) in selected_ids
    assert "UNCONFIRMED FIGURE." not in " ".join(
        Block.objects.filter(id__in=selected_ids).values_list("content_md", flat=True)
    )


def test_block_above_thread_sensitivity_excluded(joseph, thread):
    from apps.decks.assembly import assemble_deck

    lib = _anchor_library(joseph)
    # A confidential extra stat on a non-restricted (public_safe) thread is excluded.
    confidential = _block(
        joseph,
        type=Block.Type.STAT,
        sensitivity=Block.Sensitivity.CONFIDENTIAL,
        content_md="Confidential figure.",
        version=3,
    )
    p_get, p_compile, p_gate, p_notify = _patched()
    with p_get, p_compile, p_gate, p_notify:
        deck = assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    selected_ids = {bid for ids in deck.block_versions.values() for bid in ids}
    assert str(confidential.id) not in selected_ids


# -------------------------------------------------------------------------
# (d) required slot with no confirmed block — HARD error naming slide+field
# -------------------------------------------------------------------------


def test_required_slot_empty_raises_naming_slide_and_field(joseph, thread):
    from apps.decks.assembly import DeckAssemblyError, assemble_deck

    # full library EXCEPT the required ask slot
    _block(joseph, type=Block.Type.CLAIM, source_ref="wiki:m300")
    _block(joseph, type=Block.Type.PILLAR_DESCRIPTION, source_ref="wiki:cc")
    _block(joseph, type=Block.Type.STAT, source_ref="wiki:10bn")
    p_get, p_compile, p_gate, p_notify = _patched()
    with p_get, p_compile, p_gate, p_notify:
        with pytest.raises(DeckAssemblyError) as exc:
            assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    msg = str(exc.value)
    assert "ask" in msg.lower()


# -------------------------------------------------------------------------
# (e) personalization: voiced → gated; findings land + un-sendable; citations
# -------------------------------------------------------------------------


def test_personalization_is_voiced_then_gated(joseph, thread):
    from apps.decks.assembly import assemble_deck

    _anchor_library(joseph)
    with patch("apps.decks.assembly.get_dossier", return_value=DOSSIER), patch(
        "apps.decks.assembly.compile_dossier", return_value=DOSSIER
    ), patch("apps.decks.assembly.apply_voice", side_effect=lambda t: t + " ✓") as voiced, patch(
        "apps.decks.assembly.check_gate", return_value=PASS_GATE
    ) as gated, patch(
        "apps.decks.assembly.notify"
    ):
        deck = assemble_deck(thread, "philanthropy_anchor", ask_amount="$25m", presenter=joseph)
    assert voiced.called
    assert gated.called
    assert deck.gate_id == "g-pass"
    assert deck.status == DeckRegistry.Status.DRAFT


def test_gate_finding_lands_on_registry_and_marks_unsendable(joseph, thread):
    from apps.decks.assembly import assemble_deck

    _anchor_library(joseph)
    with patch("apps.decks.assembly.get_dossier", return_value=DOSSIER), patch(
        "apps.decks.assembly.compile_dossier", return_value=DOSSIER
    ), patch("apps.decks.assembly.apply_voice", side_effect=lambda t: t), patch(
        "apps.decks.assembly.check_gate", return_value=FLAG_GATE
    ), patch(
        "apps.decks.assembly.notify"
    ):
        deck = assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    assert deck.findings  # a finding is recorded
    assert deck.is_sendable is False  # un-sendable
    # but still reviewable: it exists as a draft row
    assert deck.status == DeckRegistry.Status.DRAFT


def test_opening_framing_uses_hook_by_track(joseph, thread):
    from apps.decks.assembly import assemble_deck

    _anchor_library(joseph)
    with patch("apps.decks.assembly.get_dossier", return_value=DOSSIER), patch(
        "apps.decks.assembly.compile_dossier", return_value=DOSSIER
    ), patch("apps.decks.assembly.apply_voice", side_effect=lambda t: t), patch(
        "apps.decks.assembly.check_gate", return_value=PASS_GATE
    ), patch(
        "apps.decks.assembly.notify"
    ):
        deck = assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    payload = " ".join(s.get("personalization", "") for s in deck.slides_payload)
    assert "footnote in the AI decade" in payload


def test_audience_vocabulary_map_applied(joseph, thread):
    from apps.decks.assembly import assemble_deck

    _anchor_library(joseph)
    with patch("apps.decks.assembly.get_dossier", return_value=DOSSIER), patch(
        "apps.decks.assembly.compile_dossier", return_value=DOSSIER
    ), patch("apps.decks.assembly.apply_voice", side_effect=lambda t: t), patch(
        "apps.decks.assembly.check_gate", return_value=PASS_GATE
    ), patch(
        "apps.decks.assembly.notify"
    ):
        deck = assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    blob = " ".join(s.get("personalization", "") for s in deck.slides_payload).lower()
    # Rockefeller (philanthropy_anchor) → "catalytic capital" vocabulary
    assert "catalytic capital" in blob


def test_ask_slide_uses_ask_amount(joseph, thread):
    from apps.decks.assembly import assemble_deck

    _anchor_library(joseph)
    with patch("apps.decks.assembly.get_dossier", return_value=DOSSIER), patch(
        "apps.decks.assembly.compile_dossier", return_value=DOSSIER
    ), patch("apps.decks.assembly.apply_voice", side_effect=lambda t: t), patch(
        "apps.decks.assembly.check_gate", return_value=PASS_GATE
    ), patch(
        "apps.decks.assembly.notify"
    ):
        deck = assemble_deck(thread, "philanthropy_anchor", ask_amount="$25m", presenter=joseph)
    blob = " ".join(s.get("personalization", "") for s in deck.slides_payload)
    assert "$25m" in blob


def test_untraceable_generated_claim_is_flagged(joseph, thread):
    from apps.decks.assembly import assemble_deck

    # Library where the claim block has NO source_ref and the dossier has NO
    # sources → the opening framing cannot cite anything → "untraceable".
    _block(joseph, type=Block.Type.CLAIM, source_ref=None)
    _block(joseph, type=Block.Type.PILLAR_DESCRIPTION, source_ref="wiki:cc")
    _block(joseph, type=Block.Type.STAT, source_ref="wiki:10bn")
    _block(joseph, type=Block.Type.ASK, source_ref="wiki:ask")
    no_source = dict(DOSSIER, sources=[], hook_by_track={}, hooks={})
    with patch("apps.decks.assembly.get_dossier", return_value=no_source), patch(
        "apps.decks.assembly.compile_dossier", return_value=no_source
    ), patch("apps.decks.assembly.apply_voice", side_effect=lambda t: t), patch(
        "apps.decks.assembly.check_gate", return_value=PASS_GATE
    ), patch(
        "apps.decks.assembly.notify"
    ):
        deck = assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    flat = " ".join(str(s) for s in deck.slides_payload).lower()
    assert "untraceable" in flat


# -------------------------------------------------------------------------
# (f) registry row + notify(DECK_READY)
# -------------------------------------------------------------------------


def test_registry_row_written_with_full_surface(joseph, thread):
    from apps.decks.assembly import assemble_deck

    lib = _anchor_library(joseph)
    p_get, p_compile, p_gate, p_notify = _patched()
    with p_get, p_compile, p_gate, p_notify:
        deck = assemble_deck(thread, "philanthropy_anchor", ask_amount="$25m", presenter=joseph)
    deck.refresh_from_db()
    assert deck.thread_id == thread.id
    assert deck.skeleton_id == "philanthropy_anchor"
    assert deck.presenter_id == joseph.id
    assert deck.gate_id == "g-pass"
    assert deck.slides_url  # placeholder url from the SEAM
    assert deck.slides_id
    assert deck.status == DeckRegistry.Status.DRAFT
    # block_versions records the selected block ids per slot/type
    selected = {bid for ids in deck.block_versions.values() for bid in ids}
    assert str(lib["ask"].id) in selected


def test_notify_deck_ready_fires(joseph, thread):
    from apps.decks.assembly import assemble_deck

    _anchor_library(joseph)
    with patch("apps.decks.assembly.get_dossier", return_value=DOSSIER), patch(
        "apps.decks.assembly.compile_dossier", return_value=DOSSIER
    ), patch("apps.decks.assembly.apply_voice", side_effect=lambda t: t), patch(
        "apps.decks.assembly.check_gate", return_value=PASS_GATE
    ), patch(
        "apps.decks.assembly.notify"
    ) as notify_mock:
        assemble_deck(thread, "philanthropy_anchor", presenter=joseph)
    notify_mock.assert_called_once()
    kwargs = notify_mock.call_args.kwargs
    args = notify_mock.call_args.args
    event = kwargs.get("event_type") or (args[1] if len(args) > 1 else None)
    from apps.notifications.models import EventType

    assert event == EventType.DECK_READY


# -------------------------------------------------------------------------
# slides + voice SEAMs
# -------------------------------------------------------------------------


def test_slides_render_seam_returns_placeholder(db):
    from apps.decks import slides

    out = slides.render({"slides_payload": [{"slide": 1}]})
    assert out["slides_url"]
    assert out["slides_id"]


def test_apply_voice_seam_is_identity_when_service_down():
    from apps.decks.voice import apply_voice

    # Degrades to identity (returns the input) when the agent-service is unavailable.
    assert apply_voice("Anchor the catalytic-capital round.") == "Anchor the catalytic-capital round."
