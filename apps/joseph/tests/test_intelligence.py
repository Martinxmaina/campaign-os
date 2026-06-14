"""Tests for apps.joseph.intelligence — the single JosephIntelligence seam.

brief() maps a thread+dossier onto the L0 editorial card (and L1/L2 bodies),
proposals() merges notifications + Joseph's PENDING posts + unlinked calendar
events into ActionCard dicts, and ask() is a not-yet-connected stub. The
external "knows-Joseph-end-to-end" endpoint swaps the impl behind this class.
"""
from unittest.mock import patch

import pytest

from apps.joseph.intelligence import JosephIntelligence
from apps.joseph.views import _can_access_joseph


# --------------------------------------------------------------------------
# brief() — L0/L1/L2 mapping onto the existing Dossier
# --------------------------------------------------------------------------

THREAD = {
    "id": "t1",
    "org": "Rockefeller Foundation",
    "track": "climate",
    "stage": "qualify",
    "dossier_id": "d1",
    "state": {"contact_name": "Dr. Rajiv Shah", "contact_role": "President"},
}
DOSSIER = {
    "id": "d1",
    "entity": "Rockefeller Foundation",
    "summary": "Closing a $500M Africa climate window this quarter.",
    "body_md": "## Overview\nLong-form dossier body.",
    "sources": [{"ref": "s1", "trust": 0.9}, {"ref": "s2", "trust": 0.8}],
    "red_flags": ["Slow legal", "Board reshuffle", "FX exposure", "extra-ignored"],
    "hooks": {"climate": "Lead with the SE4ALL precedent."},
    "meta": {"warm_path": "Intro via Dr. Shah's chief of staff."},
    "updated_at": "2026-06-14T10:00:00Z",
    "status": "ready",
    "thread_id": "t1",
}


def _patch_readers(thread=THREAD, dossier=DOSSIER):
    return (
        patch("apps.joseph.intelligence.readers.get_thread", return_value=thread),
        patch("apps.joseph.intelligence.readers.get_dossier", return_value=dossier),
    )


@pytest.mark.django_db
def test_brief_l0_maps_dossier_to_editorial_card():
    pt, pd = _patch_readers()
    with pt, pd:
        card = JosephIntelligence().brief("t1", "l0")
    assert "Rockefeller Foundation" in card["who"]
    assert "Dr. Rajiv Shah" in card["who"]
    assert card["why_now"] == DOSSIER["summary"]
    assert card["hook"] == "Lead with the SE4ALL precedent."
    assert card["red_flags"] == ["Slow legal", "Board reshuffle", "FX exposure"]  # capped at 3
    assert card["warm_path"] == "Intro via Dr. Shah's chief of staff."
    assert card["freshness"]["sources"] == 2
    assert card["freshness"]["updated_at"] == DOSSIER["updated_at"]


@pytest.mark.django_db
def test_brief_l0_hook_falls_back_to_first_hook_when_track_absent():
    thread = {**THREAD, "track": "energy"}  # no 'energy' key in hooks
    pt, pd = _patch_readers(thread=thread)
    with pt, pd:
        card = JosephIntelligence().brief("t1", "l0")
    assert card["hook"] == "Lead with the SE4ALL precedent."


@pytest.mark.django_db
def test_brief_l0_warm_path_defaults_to_cold_approach():
    dossier = {**DOSSIER, "meta": {}}
    pt, pd = _patch_readers(dossier=dossier)
    with pt, pd:
        card = JosephIntelligence().brief("t1", "l0")
    assert card["warm_path"] == "cold approach"


@pytest.mark.django_db
def test_brief_l1_returns_dossier_body_md():
    pt, pd = _patch_readers()
    with pt, pd:
        out = JosephIntelligence().brief("t1", "l1")
    assert out["tier"] == "l1"
    assert out["body_md"] == DOSSIER["body_md"]


@pytest.mark.django_db
def test_brief_l2_uses_wiki_page_then_falls_back_to_body_md():
    pt, pd = _patch_readers()
    page = {"slug": "rockefeller-foundation", "tier": "l2", "content": "WIKI BODY"}
    with pt, pd, patch("apps.joseph.intelligence.readers.get_page", return_value=page) as gp:
        out = JosephIntelligence().brief("t1", "l2")
    # slugified entity used to fetch the wiki page
    assert gp.call_args[0][0] == "rockefeller-foundation"
    assert out["body_md"] == "WIKI BODY"

    with pt, pd, patch("apps.joseph.intelligence.readers.get_page", return_value={}):
        out2 = JosephIntelligence().brief("t1", "l2")
    assert out2["body_md"] == DOSSIER["body_md"]  # fallback


@pytest.mark.django_db
def test_brief_no_dossier_returns_empty_card():
    pt = patch("apps.joseph.intelligence.readers.get_thread", return_value={"id": "t1", "org": "X"})
    pd = patch("apps.joseph.intelligence.readers.get_dossier", return_value={})
    with pt, pd:
        card = JosephIntelligence().brief("t1", "l0")
    assert card["has_dossier"] is False


# --------------------------------------------------------------------------
# proposals() — merge of three sources into ActionCard dicts
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_proposals_merges_three_sources_urgent_first(workspace):
    from apps.composer.models import Post

    post = Post.objects.create(
        workspace=workspace, title="Draft on minerals", caption="x",
        review_state=Post.ReviewState.PENDING,
    )

    notif = {"id": "n1", "kind": "intro", "body": "Warm intro available", "urgent": True,
             "action": {"href": "/x"}}

    # An unlinked calendar event (the Task-2 model surfaced as a linkage suggestion).
    cal = {"id": "c1", "title": "Rockefeller sync", "start": "2026-06-15T09:00:00Z"}

    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[notif]), \
         patch("apps.joseph.intelligence.JosephIntelligence._unlinked_calendar_events", return_value=[cal]):
        cards = JosephIntelligence().proposals(workspace=workspace, user=None)

    kinds = [c["kind"] for c in cards]
    assert "notification" in kinds
    assert "content_review" in kinds
    assert "calendar_link" in kinds
    # every card carries the ActionCard contract
    for c in cards:
        assert set(["kind", "title", "subtitle", "actions", "href"]).issubset(c.keys())
        assert isinstance(c["actions"], list)
    # urgent notification sorts before non-urgent items
    assert cards[0]["kind"] == "notification"
    # the content_review card points at Joseph's content queue / the post
    review_card = next(c for c in cards if c["kind"] == "content_review")
    assert str(post.id) in review_card["href"] or "content" in review_card["href"]


@pytest.mark.django_db
def test_proposals_degrades_when_everything_empty(workspace):
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]), \
         patch("apps.joseph.intelligence.JosephIntelligence._unlinked_calendar_events", return_value=[]):
        cards = JosephIntelligence().proposals(workspace=workspace, user=None)
    assert cards == []


# --------------------------------------------------------------------------
# ask() — not-yet-connected stub
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_ask_returns_not_connected_stub():
    out = JosephIntelligence().ask("What should I say to Rockefeller?")
    assert out["connected"] is False
    assert "message" in out


# --------------------------------------------------------------------------
# _can_access_joseph — role gate
# --------------------------------------------------------------------------


class _Req:
    def __init__(self, *, is_staff=False, workspace_role=None):
        self.user = type("U", (), {"is_staff": is_staff})()
        if workspace_role is not None:
            self.workspace_membership = type("M", (), {"workspace_role": workspace_role})()
        else:
            self.workspace_membership = None


@pytest.mark.parametrize("role,expected", [
    ("owner", True),
    ("admin", True),
    ("principal", True),
    ("manager", False),
    ("editor", False),
    ("member", False),
    ("viewer", False),
    (None, False),
])
def test_can_access_joseph_by_role(role, expected):
    assert _can_access_joseph(_Req(workspace_role=role)) is expected


def test_can_access_joseph_staff_always_true():
    assert _can_access_joseph(_Req(is_staff=True)) is True
    assert _can_access_joseph(_Req(is_staff=True, workspace_role="viewer")) is True
