"""Tests for the deck review screen + version history + stale-figure report (TB.5 Task 3).

The review surface is Joseph's window onto an assembled deck:

  * ``GET /joseph/decks/<deck_id>/`` renders the review screen — a slide preview
    (the rendered slide payload / placeholder seam embed), the gate status + any
    flagged findings, the block list with citations, and a version-history rail.
    Role-gated by ``_can_access_joseph`` + CSP-safe (nonce'd scripts, no inline
    handlers).
  * Each assembly/edit cycle is a ``DeckVersion`` (a block_versions snapshot +
    the slides payload). ``POST /joseph/decks/<deck_id>/revert/<version_id>/``
    restores a version by writing a NEW version row (never in-place).
  * ``GET /joseph/decks/stale/`` lists *sent* decks whose registry holds a block
    version that has since been superseded — the offending block + the deck.
  * A draft deck appears in the decks index (Joseph's action queue surface).

Role-gating reuses ``apps.joseph.views._can_access_joseph``; no network (the
render is the deterministic SEAM, the gate is not called by the review screen).
The ``joseph``/``viewer`` fixtures ``force_login`` the shared pytest ``client``,
so tests take ``client`` as a parameter to drive the already-authed session.
"""
import uuid

import pytest
from django.urls import reverse

from apps.crm.models import Organization, OutreachThread
from apps.decks.models import Block, DeckRegistry, DeckVersion


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
    """An ordinary workspace member — must not reach the deck review surface."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    u = User.objects.create_user(
        email="deckviewer@example.com", password="x", name="Viewer", tos_accepted_at=timezone.now()
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


def _deck(thread, presenter, *, status=DeckRegistry.Status.DRAFT, block_versions=None,
          findings=None, payload=None, gate_id="g-pass"):
    return DeckRegistry.objects.create(
        thread=thread,
        skeleton_id="philanthropy_anchor",
        presenter=presenter,
        block_versions=block_versions or {},
        slides_payload=payload
        or [{"slide": 0, "block_ids": [], "content_md": "Mission 300.",
             "personalization": "Africa will not be a footnote.", "citations": ["wiki:m300"]}],
        findings=findings or [],
        gate_id=gate_id,
        slides_url="https://docs.google.com/presentation/d/slides-x/edit",
        slides_id="slides-x",
        status=status,
    )


# -------------------------------------------------------------------------
# DeckVersion model + record helper
# -------------------------------------------------------------------------


def test_deckversion_records_a_snapshot(joseph, thread):
    from apps.decks.models import record_version

    deck = _deck(thread, joseph, block_versions={"0": ["b1"]})
    v = record_version(deck, reason="assembled")
    assert isinstance(v, DeckVersion)
    assert v.deck_id == deck.id
    assert v.block_versions == {"0": ["b1"]}
    assert v.slides_payload == deck.slides_payload
    assert v.reason == "assembled"


def test_deckversion_numbers_increment_per_deck(joseph, thread):
    from apps.decks.models import record_version

    deck = _deck(thread, joseph)
    v1 = record_version(deck, reason="assembled")
    v2 = record_version(deck, reason="edited")
    assert v2.number == v1.number + 1


# -------------------------------------------------------------------------
# review screen: GET /joseph/decks/<deck_id>/
# -------------------------------------------------------------------------


def test_review_screen_renders_full_surface(joseph, client, thread):
    block = _block(joseph)
    deck = _deck(
        thread,
        joseph,
        block_versions={"0": [str(block.id)]},
        payload=[{
            "slide": 0,
            "block_ids": [str(block.id)],
            "content_md": "Mission 300.",
            "personalization": "Africa will not be a footnote.",
            "citations": ["wiki:mission-300", str(block.id)],
        }],
    )
    from apps.decks.models import record_version
    record_version(deck, reason="assembled")

    resp = client.get(reverse("decks:review", args=[deck.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # slide preview (payload / placeholder embed for the seam)
    assert "Africa will not be a footnote." in body
    assert deck.slides_url in body or "slides-x" in body
    # gate status surfaced
    assert "g-pass" in body or "gate" in body.lower()
    # block list with citations
    assert "wiki:mission-300" in body
    # version-history rail present
    assert "version" in body.lower()
    # CSP-safe: no inline handlers
    assert "onclick=" not in body
    assert "onsubmit=" not in body


def test_review_screen_shows_findings_when_flagged(joseph, client, thread):
    deck = _deck(
        thread, joseph,
        findings=[{"rule": "token_language", "match": "guaranteed"}],
        gate_id="g-flag",
    )
    resp = client.get(reverse("decks:review", args=[deck.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "token_language" in body or "guaranteed" in body
    assert deck.is_sendable is False


def test_review_screen_role_gated(viewer, client, thread):
    deck = _deck(thread, viewer)
    resp = client.get(reverse("decks:review", args=[deck.id]))
    assert resp.status_code == 403


def test_review_screen_unknown_deck_404(joseph, client):
    resp = client.get(reverse("decks:review", args=[uuid.uuid4()]))
    assert resp.status_code == 404


# -------------------------------------------------------------------------
# revert: POST /joseph/decks/<deck_id>/revert/<version_id>/
# -------------------------------------------------------------------------


def test_revert_restores_version_as_new_row(joseph, client, thread):
    from apps.decks.models import record_version

    deck = _deck(thread, joseph, block_versions={"0": ["old"]})
    v1 = record_version(deck, reason="assembled")
    # the deck moves on (an edit changes the live state + records a new version)
    deck.block_versions = {"0": ["new"]}
    deck.slides_payload = [{"slide": 0, "personalization": "edited", "citations": []}]
    deck.save(update_fields=["block_versions", "slides_payload", "updated_at"])
    record_version(deck, reason="edited")

    resp = client.post(reverse("decks:revert", args=[deck.id, v1.id]))
    assert resp.status_code in (200, 302)
    deck.refresh_from_db()
    # the deck's live state matches v1 again
    assert deck.block_versions == {"0": ["old"]}
    # restore is a NEW version row, never in-place: 3 versions now exist
    assert DeckVersion.objects.filter(deck=deck).count() == 3
    latest = DeckVersion.objects.filter(deck=deck).order_by("-number").first()
    assert latest.block_versions == {"0": ["old"]}
    assert "revert" in latest.reason.lower()


def test_revert_role_gated(viewer, client, thread):
    from apps.decks.models import record_version

    deck = _deck(thread, viewer)
    v1 = record_version(deck, reason="assembled")
    resp = client.post(reverse("decks:revert", args=[deck.id, v1.id]))
    assert resp.status_code == 403


# -------------------------------------------------------------------------
# stale-figure report: GET /joseph/decks/stale/
# -------------------------------------------------------------------------


def test_stale_report_lists_sent_decks_with_superseded_block(joseph, client, thread):
    # An original stat block that a sent deck pinned…
    old = _block(joseph, type=Block.Type.STAT, content_md="$10bn mobilised.", version=1)
    # …then a corrected v2 supersedes it in the live library.
    new = _block(joseph, type=Block.Type.STAT, content_md="$12bn mobilised.", version=2)
    old.superseded_by = new
    old.save(update_fields=["superseded_by"])

    sent = _deck(
        thread, joseph,
        status=DeckRegistry.Status.SENT,
        block_versions={"2": [str(old.id)]},
    )
    # a fresh sent deck pinning only the current block must NOT show up
    fresh = _deck(
        thread, joseph,
        status=DeckRegistry.Status.SENT,
        block_versions={"2": [str(new.id)]},
    )

    resp = client.get(reverse("decks:stale"))
    assert resp.status_code == 200
    body = resp.content.decode()
    # the offending block + the deck are named
    assert str(old.id) in body
    assert str(sent.id) in body
    # the fresh deck (no superseded block) is not flagged
    assert str(fresh.id) not in body


def test_stale_report_ignores_draft_decks(joseph, client, thread):
    old = _block(joseph, type=Block.Type.STAT, version=1)
    new = _block(joseph, type=Block.Type.STAT, version=2)
    old.superseded_by = new
    old.save(update_fields=["superseded_by"])
    # a DRAFT deck holding the superseded block must NOT appear (only sent decks).
    draft = _deck(
        thread, joseph,
        status=DeckRegistry.Status.DRAFT,
        block_versions={"2": [str(old.id)]},
    )
    resp = client.get(reverse("decks:stale"))
    assert resp.status_code == 200
    assert str(draft.id) not in resp.content.decode()


def test_stale_report_role_gated(viewer, client, thread):
    resp = client.get(reverse("decks:stale"))
    assert resp.status_code == 403


# -------------------------------------------------------------------------
# decks index: a draft deck appears in Joseph's action queue
# -------------------------------------------------------------------------


def test_decks_index_lists_draft_decks(joseph, client, thread):
    draft = _deck(thread, joseph, status=DeckRegistry.Status.DRAFT)
    resp = client.get(reverse("decks:index"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert str(draft.id) in body or "Rockefeller Foundation" in body


def test_decks_index_role_gated(viewer, client, thread):
    resp = client.get(reverse("decks:index"))
    assert resp.status_code == 403
