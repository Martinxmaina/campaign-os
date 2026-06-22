"""Audience deck skeletons (TB.5 Task 1).

A *skeleton* is the per-audience slide order. Each slot in ``slide_order``
declares the ``accepted_block_types`` that may fill it, whether the slot is
``required`` (a missing required slot is a hard assembly error in Task 2), and
a ``max_blocks`` cap. Skeletons are static structure — no DB, no I/O — so the
assembly engine can reason about a deck's shape before touching the library.

``validate(skeleton_id, blocks_qs)`` is the library-coverage check: it returns
``(ok, missing)`` where ``missing`` is every accepted block type that has *zero*
confirmed blocks in the candidate set. Only ``confirmed`` blocks count.
"""
from __future__ import annotations


def _slot(types, *, required=True, max_blocks=1):
    return {"accepted_block_types": list(types), "required": required, "max_blocks": max_blocks}


# Five audience skeletons. Block types reuse Block.Type values.
SKELETONS: dict[str, dict] = {
    # Big philanthropic anchor (Rockefeller-style): vision -> credibility -> ask.
    "philanthropy_anchor": {
        "title": "Philanthropy anchor",
        "slide_order": [
            _slot(["claim"]),  # opening framing
            _slot(["pillar_description"], max_blocks=3),
            _slot(["stat"], max_blocks=3),
            _slot(["case_study"], required=False, max_blocks=2),
            _slot(["governance"], required=False),
            _slot(["team", "bio"], required=False, max_blocks=4),
            _slot(["ask"]),
            _slot(["closing"], required=False),
        ],
    },
    # Bilateral technical-assistance funder (GIZ-style): problem -> programme -> TA scope.
    "bilateral_ta": {
        "title": "Bilateral / technical assistance",
        "slide_order": [
            _slot(["claim"]),
            _slot(["pillar_description"], max_blocks=2),
            _slot(["case_study", "precedent"], max_blocks=2),
            _slot(["stat"], required=False, max_blocks=3),
            _slot(["governance"], required=False),
            _slot(["ask"]),
            _slot(["closing"], required=False),
        ],
    },
    # Corporate sponsor (brand/visibility lens): proposition -> reach -> partnership ask.
    "corporate_sponsor": {
        "title": "Corporate sponsor",
        "slide_order": [
            _slot(["claim"]),
            _slot(["stat"], max_blocks=3),
            _slot(["case_study"], required=False, max_blocks=2),
            _slot(["precedent"], required=False, max_blocks=2),
            _slot(["ask"]),
            _slot(["closing"], required=False),
        ],
    },
    # DFI (blended-finance lens): thesis -> track record -> governance -> structured ask.
    "dfi": {
        "title": "Development finance institution",
        "slide_order": [
            _slot(["claim"]),
            _slot(["stat"], max_blocks=4),
            _slot(["precedent"], max_blocks=2),
            _slot(["governance"]),
            _slot(["team", "bio"], required=False, max_blocks=4),
            _slot(["ask"]),
            _slot(["closing"], required=False),
        ],
    },
    # Internal principal brief (Joseph reads it himself): no external polish.
    "principal_brief": {
        "title": "Principal brief",
        "slide_order": [
            _slot(["claim"]),
            _slot(["stat"], max_blocks=5),
            _slot(["case_study", "precedent"], required=False, max_blocks=4),
            _slot(["governance"], required=False),
            _slot(["ask"], required=False),
        ],
    },
}


def get(skeleton_id: str) -> dict | None:
    """Return the skeleton dict for ``skeleton_id``, or ``None`` if unknown."""
    return SKELETONS.get(skeleton_id)


def accepted_types(skeleton_id: str) -> set[str]:
    """The union of every accepted block type across the skeleton's slots."""
    sk = get(skeleton_id)
    if sk is None:
        return set()
    return {t for slot in sk["slide_order"] for t in slot["accepted_block_types"]}


def validate(skeleton_id: str, blocks_qs) -> tuple[bool, list[str]]:
    """Check the candidate ``blocks_qs`` can fill every accepted type.

    Returns ``(ok, missing)`` where ``missing`` is every accepted block type
    with zero *confirmed* blocks in the set. Only ``confirmed`` blocks count.
    """
    from apps.decks.models import Block

    needed = accepted_types(skeleton_id)
    if not needed:
        return False, []

    have = set(
        blocks_qs.filter(confirmation_status=Block.Confirmation.CONFIRMED).values_list(
            "type", flat=True
        )
    )
    missing = sorted(needed - have)
    return (not missing), missing
