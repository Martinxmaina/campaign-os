"""Tests for the audience deck skeletons + their validation (TB.5 Task 1).

A skeleton is the per-audience slide order with, for every slide slot, the
``accepted_block_types`` that may fill it, whether the slot is ``required``,
and a ``max_blocks`` cap. ``skeletons.validate`` confirms a candidate block set
can actually fill every accepted type with at least one *confirmed* block.
"""
import pytest

from apps.decks import skeletons
from apps.decks.models import Block

ALL_SKELETONS = {
    "philanthropy_anchor",
    "bilateral_ta",
    "corporate_sponsor",
    "dfi",
    "principal_brief",
}


@pytest.fixture
def joseph(db, user):
    return user


# -------------------------------------------------------------------------
# get() — the five skeletons + their shape
# -------------------------------------------------------------------------


def test_get_returns_the_five_skeletons():
    for sid in ALL_SKELETONS:
        sk = skeletons.get(sid)
        assert sk is not None, sid


def test_get_unknown_skeleton_returns_none():
    assert skeletons.get("does_not_exist") is None


def test_skeleton_has_slide_order_and_typed_slots():
    sk = skeletons.get("philanthropy_anchor")
    assert isinstance(sk["slide_order"], list)
    assert len(sk["slide_order"]) >= 1
    for slot in sk["slide_order"]:
        assert isinstance(slot["accepted_block_types"], list)
        assert len(slot["accepted_block_types"]) >= 1
        assert isinstance(slot["required"], bool)
        assert isinstance(slot["max_blocks"], int)
        assert slot["max_blocks"] >= 1
        # every accepted type is a real Block type
        for t in slot["accepted_block_types"]:
            assert t in {v for v, _ in Block.Type.choices}


def test_every_skeleton_has_at_least_one_required_slot():
    for sid in ALL_SKELETONS:
        sk = skeletons.get(sid)
        assert any(slot["required"] for slot in sk["slide_order"]), sid


# -------------------------------------------------------------------------
# validate() — fails when an accepted type has zero confirmed blocks
# -------------------------------------------------------------------------


def _confirmed(owner, block_type, **kw):
    return Block.objects.create(
        type=block_type,
        track=kw.get("track", "ai10bn"),
        audience_type=kw.get("audience_type", Block.Audience.PHILANTHROPY_ANCHOR),
        sensitivity=Block.Sensitivity.PUBLIC_SAFE,
        confirmation_status=Block.Confirmation.CONFIRMED,
        content_md=kw.get("content_md", "x"),
        owner=owner,
    )


def test_validate_fails_when_no_confirmed_block_for_an_accepted_type(joseph):
    # No blocks at all -> every accepted type is unfilled.
    ok, missing = skeletons.validate("philanthropy_anchor", Block.objects.none())
    assert ok is False
    assert missing, "expected the unfilled accepted types to be reported"


def test_validate_ignores_unconfirmed_blocks(joseph):
    sk = skeletons.get("philanthropy_anchor")
    # Create exactly one UNCONFIRMED block for every accepted type -> still fails.
    types = {t for slot in sk["slide_order"] for t in slot["accepted_block_types"]}
    for t in types:
        Block.objects.create(
            type=t,
            track="ai10bn",
            audience_type=Block.Audience.PHILANTHROPY_ANCHOR,
            sensitivity=Block.Sensitivity.PUBLIC_SAFE,
            confirmation_status=Block.Confirmation.UNCONFIRMED,
            content_md="x",
            owner=joseph,
        )
    ok, missing = skeletons.validate("philanthropy_anchor", Block.objects.all())
    assert ok is False
    assert set(missing) == set(types)


def test_validate_passes_when_each_accepted_type_has_a_confirmed_block(joseph):
    sk = skeletons.get("philanthropy_anchor")
    types = {t for slot in sk["slide_order"] for t in slot["accepted_block_types"]}
    for t in types:
        _confirmed(joseph, t)
    ok, missing = skeletons.validate("philanthropy_anchor", Block.objects.all())
    assert ok is True
    assert missing == []
