"""Tests for the deck customisation loop (TB.5 Task 5).

The review screen's right panel offers three edit modes, each of which produces a
new ``DeckVersion`` and re-runs the gate so a deck can never drift past the wall:

  (1) **Section request** — ``POST /joseph/decks/<id>/edit/section/`` with NL text
      drives ``edits.apply_section_request`` (a deterministic SEAM for the real
      agent-service section-edit pass), re-gates the CHANGED slide(s) only, writes
      a new ``DeckVersion``, and logs an audit episode line.
  (2) **Block swap** — ``POST /joseph/decks/<id>/edit/swap/`` browses blocks
      compatible with a slot (filtered by the slot's accepted_block_types + track
      + sensitivity + confirmed only) and swaps one in, re-gates that slide, writes
      a new version.
  (3) **Direct edit + sync** — ``POST /joseph/decks/<id>/sync/`` pulls the current
      Slides state back in (SEAM) and re-gate-verifies the WHOLE deck.

All three are role-gated by ``apps.joseph.views._can_access_joseph`` + CSP-safe,
and revert (Task 3) still works across edits (each edit is a real version row).

The gate is a SEAM here: tests monkeypatch ``apps.decks.edits.check_gate`` so no
network is touched and the re-gate behaviour (pass vs flag, which slides) is
asserted directly.
"""
import logging
import uuid

import pytest
from django.urls import reverse

from apps.crm.models import Organization, OutreachThread
from apps.decks.models import Block, DeckRegistry, DeckVersion, record_version


# -------------------------------------------------------------------------
# fixtures
# -------------------------------------------------------------------------


@pytest.fixture
def joseph(client, org_owner, workspace):
    """Joseph = an owner of the workspace (can reach the principal surface)."""
    from apps.members.models import WorkspaceMembership

    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def viewer(client, db, organization, workspace):
    """An ordinary workspace member — must not reach the deck edit surface."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    u = User.objects.create_user(
        email="deckeditviewer@example.com", password="x", name="Viewer",
        tos_accepted_at=timezone.now(),
    )
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


@pytest.fixture
def thread(db):
    org = Organization.objects.create(name="Rockefeller Foundation")
    # philanthropy_anchor skeleton + ai10bn track (matches the seed library audience).
    return OutreachThread.objects.create(org=org, track="ai10bn", restricted=False)


def _block(owner, **kw):
    defaults = dict(
        type=Block.Type.STAT,
        track="ai10bn",
        audience_type=Block.Audience.PHILANTHROPY_ANCHOR,
        sensitivity=Block.Sensitivity.PUBLIC_SAFE,
        confirmation_status=Block.Confirmation.CONFIRMED,
        content_md="$10bn mobilised.",
        source_ref="wiki:mission-300",
        owner=owner,
    )
    defaults.update(kw)
    return Block.objects.create(**defaults)


def _deck(thread, presenter, *, status=DeckRegistry.Status.DRAFT, block_versions=None,
          findings=None, payload=None, gate_id="g-pass"):
    deck = DeckRegistry.objects.create(
        thread=thread,
        skeleton_id="philanthropy_anchor",
        presenter=presenter,
        block_versions=block_versions or {},
        slides_payload=payload
        or [
            {"slide": 0, "accepted_block_types": ["claim"], "block_ids": [],
             "content_md": "Mission 300.", "personalization": "Africa will not be a footnote.",
             "citations": ["wiki:m300"]},
            {"slide": 1, "accepted_block_types": ["stat"], "block_ids": [],
             "content_md": "$10bn mobilised.", "personalization": "Framed for catalytic capital.",
             "citations": ["wiki:m300"]},
        ],
        findings=findings or [],
        gate_id=gate_id,
        slides_url="https://docs.google.com/presentation/d/slides-x/edit",
        slides_id="slides-x",
        status=status,
    )
    # Every deck starts life with its assembly version (so revert has a baseline).
    record_version(deck, reason="assembled", created_by=presenter)
    return deck


def _pass_gate(*args, **kwargs):
    return {"verdict": "pass", "findings": [], "gate_id": "g-reedit", "content_hash": "h"}


def _flag_gate(*args, **kwargs):
    return {
        "verdict": "fail",
        "findings": [{"rule": "token_language", "match": "guaranteed"}],
        "gate_id": "g-flagged",
        "content_hash": "h",
    }


# =========================================================================
# (1) Section request
# =========================================================================


def test_section_request_edits_slide_regates_and_versions(joseph, client, thread, monkeypatch):
    monkeypatch.setattr("apps.decks.edits.check_gate", _pass_gate)
    deck = _deck(thread, joseph)
    before = DeckVersion.objects.filter(deck=deck).count()

    resp = client.post(
        reverse("decks:edit_section", args=[deck.id]),
        {"slide": "1", "instruction": "Sharpen the framing for a climate-finance audience."},
    )
    assert resp.status_code in (200, 302)

    deck.refresh_from_db()
    # the deterministic SEAM left a mark on the targeted slide's generated layer
    edited = deck.slides_payload[1]
    assert "climate-finance" in edited["personalization"].lower() or edited.get("edited")
    # a NEW version row was written (assembly + this edit)
    assert DeckVersion.objects.filter(deck=deck).count() == before + 1
    latest = DeckVersion.objects.filter(deck=deck).order_by("-number").first()
    assert "section" in latest.reason.lower() or "edit" in latest.reason.lower()


def test_section_request_regates_only_the_changed_slide(joseph, client, thread, monkeypatch):
    """The re-gate runs on the CHANGED slide(s) only, not the whole deck body."""
    captured = {}

    def _spy(content, *args, **kwargs):
        captured["content"] = content
        return _pass_gate()

    monkeypatch.setattr("apps.decks.edits.check_gate", _spy)
    deck = _deck(thread, joseph)
    client.post(
        reverse("decks:edit_section", args=[deck.id]),
        {"slide": "1", "instruction": "Make slide one tighter."},
    )
    # The gated content is the edited slide-1 line — NOT slide 0's opening framing.
    assert "Africa will not be a footnote." not in captured["content"]


def test_section_request_gate_finding_marks_unsendable(joseph, client, thread, monkeypatch):
    monkeypatch.setattr("apps.decks.edits.check_gate", _flag_gate)
    deck = _deck(thread, joseph)
    client.post(
        reverse("decks:edit_section", args=[deck.id]),
        {"slide": "1", "instruction": "We guaranteed returns."},
    )
    deck.refresh_from_db()
    assert deck.is_sendable is False
    assert any(f.get("rule") == "token_language" for f in deck.findings)


def test_section_request_logs_an_audit_episode(joseph, client, thread, monkeypatch, caplog):
    monkeypatch.setattr("apps.decks.edits.check_gate", _pass_gate)
    deck = _deck(thread, joseph)
    with caplog.at_level(logging.INFO, logger="apps.decks"):
        client.post(
            reverse("decks:edit_section", args=[deck.id]),
            {"slide": "1", "instruction": "Tighten it."},
        )
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert str(deck.id) in joined
    assert "section" in joined.lower() or "edit" in joined.lower()


def test_section_request_role_gated(viewer, client, thread, monkeypatch):
    monkeypatch.setattr("apps.decks.edits.check_gate", _pass_gate)
    deck = _deck(thread, viewer)
    resp = client.post(
        reverse("decks:edit_section", args=[deck.id]),
        {"slide": "1", "instruction": "x"},
    )
    assert resp.status_code == 403


def test_section_request_requires_post(joseph, client, thread):
    deck = _deck(thread, joseph)
    resp = client.get(reverse("decks:edit_section", args=[deck.id]))
    assert resp.status_code == 405


# =========================================================================
# (2) Block swap
# =========================================================================


def test_compatible_blocks_filters_by_slot_track_sensitivity_confirmed(joseph, thread):
    from apps.decks.edits import compatible_blocks

    # slot 1 accepts ["stat"]; the thread is ai10bn / public_safe ceiling.
    good = _block(joseph, type=Block.Type.STAT, content_md="$12bn mobilised.")
    wrong_type = _block(joseph, type=Block.Type.CLAIM, content_md="A claim.")
    wrong_track = _block(joseph, type=Block.Type.STAT, track="programs", content_md="Other track.")
    too_sensitive = _block(
        joseph, type=Block.Type.STAT, sensitivity=Block.Sensitivity.CONFIDENTIAL,
        content_md="Confidential.",
    )
    unconfirmed = _block(
        joseph, type=Block.Type.STAT, confirmation_status=Block.Confirmation.UNCONFIRMED,
        content_md="Unconfirmed.",
    )

    deck = _deck(thread, joseph, block_versions={"1": []})
    candidates = list(compatible_blocks(deck, slot=1))
    ids = {str(b.id) for b in candidates}
    assert str(good.id) in ids
    assert str(wrong_type.id) not in ids
    assert str(wrong_track.id) not in ids
    assert str(too_sensitive.id) not in ids
    assert str(unconfirmed.id) not in ids


def test_block_swap_swaps_block_regates_and_versions(joseph, client, thread, monkeypatch):
    monkeypatch.setattr("apps.decks.edits.check_gate", _pass_gate)
    old = _block(joseph, type=Block.Type.STAT, content_md="$10bn mobilised.")
    new = _block(joseph, type=Block.Type.STAT, content_md="$12bn mobilised.")
    deck = _deck(
        thread, joseph,
        block_versions={"1": [str(old.id)]},
        payload=[
            {"slide": 0, "accepted_block_types": ["claim"], "block_ids": [],
             "content_md": "Mission 300.", "personalization": "Opening.", "citations": []},
            {"slide": 1, "accepted_block_types": ["stat"], "block_ids": [str(old.id)],
             "content_md": "$10bn mobilised.", "personalization": "Framed.",
             "citations": [str(old.id)]},
        ],
    )
    before = DeckVersion.objects.filter(deck=deck).count()

    resp = client.post(
        reverse("decks:edit_swap", args=[deck.id]),
        {"slot": "1", "block_id": str(new.id)},
    )
    assert resp.status_code in (200, 302)

    deck.refresh_from_db()
    # the slot now pins the new block and the slide content reflects it
    assert deck.block_versions["1"] == [str(new.id)]
    assert "$12bn mobilised." in deck.slides_payload[1]["content_md"]
    assert DeckVersion.objects.filter(deck=deck).count() == before + 1


def test_block_swap_rejects_incompatible_block(joseph, client, thread, monkeypatch):
    """A block that fails the slot wall (wrong type/track/sensitivity) is refused."""
    monkeypatch.setattr("apps.decks.edits.check_gate", _pass_gate)
    old = _block(joseph, type=Block.Type.STAT)
    wrong_track = _block(joseph, type=Block.Type.STAT, track="programs")
    deck = _deck(thread, joseph, block_versions={"1": [str(old.id)]})
    before = DeckVersion.objects.filter(deck=deck).count()

    resp = client.post(
        reverse("decks:edit_swap", args=[deck.id]),
        {"slot": "1", "block_id": str(wrong_track.id)},
    )
    # rejected — no swap, no new version
    assert resp.status_code in (400, 422)
    deck.refresh_from_db()
    assert deck.block_versions["1"] == [str(old.id)]
    assert DeckVersion.objects.filter(deck=deck).count() == before


def test_block_swap_role_gated(viewer, client, thread, monkeypatch):
    monkeypatch.setattr("apps.decks.edits.check_gate", _pass_gate)
    block = _block(viewer, type=Block.Type.STAT)
    deck = _deck(thread, viewer, block_versions={"1": []})
    resp = client.post(
        reverse("decks:edit_swap", args=[deck.id]),
        {"slot": "1", "block_id": str(block.id)},
    )
    assert resp.status_code == 403


# =========================================================================
# (3) Direct edit + sync
# =========================================================================


def test_sync_pulls_slides_state_and_regates_whole_deck(joseph, client, thread, monkeypatch):
    gated = {}

    def _spy(content, *args, **kwargs):
        gated["content"] = content
        return _pass_gate()

    monkeypatch.setattr("apps.decks.edits.check_gate", _spy)
    # The sync SEAM returns a deck-wide edited payload (direct Slides edits pulled back).
    monkeypatch.setattr(
        "apps.decks.edits.pull_slides_state",
        lambda deck: [
            {"slide": 0, "accepted_block_types": ["claim"], "block_ids": [],
             "content_md": "Mission 300.", "personalization": "Edited in Slides directly.",
             "citations": []},
            {"slide": 1, "accepted_block_types": ["stat"], "block_ids": [],
             "content_md": "$10bn mobilised.", "personalization": "Also edited.",
             "citations": []},
        ],
    )
    deck = _deck(thread, joseph)
    before = DeckVersion.objects.filter(deck=deck).count()

    resp = client.post(reverse("decks:sync", args=[deck.id]))
    assert resp.status_code in (200, 302)

    deck.refresh_from_db()
    assert "Edited in Slides directly." in deck.slides_payload[0]["personalization"]
    # the WHOLE deck is re-gated on sync (both edited lines are in the gated body)
    assert "Edited in Slides directly." in gated["content"]
    assert "Also edited." in gated["content"]
    assert DeckVersion.objects.filter(deck=deck).count() == before + 1


def test_sync_gate_finding_marks_unsendable(joseph, client, thread, monkeypatch):
    monkeypatch.setattr("apps.decks.edits.check_gate", _flag_gate)
    monkeypatch.setattr(
        "apps.decks.edits.pull_slides_state",
        lambda deck: [
            {"slide": 0, "accepted_block_types": ["claim"], "block_ids": [],
             "content_md": "x", "personalization": "We guaranteed it.", "citations": []},
        ],
    )
    deck = _deck(thread, joseph)
    client.post(reverse("decks:sync", args=[deck.id]))
    deck.refresh_from_db()
    assert deck.is_sendable is False


def test_sync_role_gated(viewer, client, thread):
    deck = _deck(thread, viewer)
    resp = client.post(reverse("decks:sync", args=[deck.id]))
    assert resp.status_code == 403


def test_pull_slides_state_seam_degrades_to_current_payload(joseph, thread):
    """The SEAM returns the deck's current payload (no live Slides yet)."""
    from apps.decks.edits import pull_slides_state

    deck = _deck(thread, joseph)
    pulled = pull_slides_state(deck)
    assert pulled == deck.slides_payload


# =========================================================================
# revert still works across edits (Task 3 lineage holds)
# =========================================================================


def test_revert_works_after_an_edit(joseph, client, thread, monkeypatch):
    monkeypatch.setattr("apps.decks.edits.check_gate", _pass_gate)
    deck = _deck(thread, joseph)
    v1 = DeckVersion.objects.filter(deck=deck).order_by("number").first()
    original_payload = list(deck.slides_payload)

    client.post(
        reverse("decks:edit_section", args=[deck.id]),
        {"slide": "1", "instruction": "Change it."},
    )
    deck.refresh_from_db()

    resp = client.post(reverse("decks:revert", args=[deck.id, v1.id]))
    assert resp.status_code in (200, 302)
    deck.refresh_from_db()
    assert deck.slides_payload == original_payload


# =========================================================================
# review screen exposes the three-mode edit panel (CSP-safe)
# =========================================================================


def test_review_screen_renders_edit_panel(joseph, client, thread):
    block = _block(joseph, type=Block.Type.STAT)
    deck = _deck(thread, joseph, block_versions={"1": [str(block.id)]})
    resp = client.get(reverse("decks:review", args=[deck.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # the three edit affordances are present
    assert reverse("decks:edit_section", args=[deck.id]) in body
    assert reverse("decks:edit_swap", args=[deck.id]) in body
    assert reverse("decks:sync", args=[deck.id]) in body
    # CSP-safe: no inline handlers
    assert "onclick=" not in body
    assert "onsubmit=" not in body
