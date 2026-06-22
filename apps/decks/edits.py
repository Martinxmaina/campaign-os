"""Deck customisation loop (TB.5 Task 5) — section request / block swap / sync.

The review screen's edit panel drives three deck mutations. Each one re-runs the
gate and writes a new ``DeckVersion`` (so the wall is never crossed silently and
the lineage — and revert — stays intact):

  1. **Section request** — :func:`apply_section_request` takes the free-text
     instruction Joseph types and applies a *targeted* edit to one named slide's
     generated personalization line. This is the **deterministic SEAM** for the
     real agent-service section-edit pass (``# SEAM: real agent-service edit pass
     later``): today it appends the instruction's intent to the line so the edit
     is observable + testable; when wired it becomes a ``voice:joseph`` /
     section-edit agent call that rewrites the line. The caller re-gates the
     CHANGED slide(s) only.
  2. **Block swap** — :func:`compatible_blocks` browses the live library for blocks
     that pass the SAME wall the assembly engine enforces for the slot (accepted
     block types + thread track + sensitivity ceiling + confirmed ONLY).
     :func:`swap_block` swaps the chosen block into a slot and rebuilds that
     slide's content (raising :class:`SwapRejected` if the block fails the wall).
     The caller re-gates that slide.
  3. **Direct edit + sync** — :func:`pull_slides_state` is the **SEAM** that pulls
     the live Google Slides state back into the structured payload (``# SEAM: real
     Google Slides presentations.get later``). Today it degrades to the deck's
     current payload (no live Slides yet). The caller re-gate-verifies the WHOLE
     deck against the pulled state.

The gate itself is the authoritative ``apps.publisher.gate_client.check_gate``
(re-exported here so views + tests share one seam) and the voice layer is the
``apply_voice`` SEAM — neither is re-implemented.
"""
from __future__ import annotations

import logging

from apps.decks.models import Block, DeckRegistry
from apps.decks.voice import apply_voice  # noqa: F401  (kept for the live edit pass)
from apps.publisher.gate_client import GateError, check_gate  # noqa: F401

logger = logging.getLogger("apps.decks")

# Mirror the assembly wall so a swapped-in block is held to the same standard as
# an originally-assembled one (public_safe < partner_only < confidential).
_SENSITIVITY_RANK = {
    Block.Sensitivity.PUBLIC_SAFE: 0,
    Block.Sensitivity.PARTNER_ONLY: 1,
    Block.Sensitivity.CONFIDENTIAL: 2,
}
_PUBLIC_SAFE_TRACKS = {"core", "programs"}


class SwapRejected(Exception):
    """A swap-in block failed the slot wall (type / track / sensitivity / confirmed)."""


def _thread_track(deck: DeckRegistry) -> str:
    return (getattr(deck.thread, "track", "") or "").strip()


def _thread_sensitivity_ceiling(deck: DeckRegistry) -> int:
    """The thread's sensitivity ceiling as a rank (mirrors assembly._thread_sensitivity)."""
    thread = deck.thread
    if getattr(thread, "restricted", False):
        return _SENSITIVITY_RANK[Block.Sensitivity.CONFIDENTIAL]
    track = (getattr(thread, "track", "") or "").strip().lower()
    if track in _PUBLIC_SAFE_TRACKS:
        return _SENSITIVITY_RANK[Block.Sensitivity.PUBLIC_SAFE]
    return _SENSITIVITY_RANK[Block.Sensitivity.PARTNER_ONLY]


def _slide(deck: DeckRegistry, slide_index: int) -> dict | None:
    payload = deck.slides_payload or []
    if 0 <= slide_index < len(payload):
        return payload[slide_index]
    return None


def _slot_accepted_types(deck: DeckRegistry, slot: int) -> list[str]:
    """The accepted block types for ``slot`` — read off the deck's own payload.

    The payload carries ``accepted_block_types`` per slide (stamped at assembly),
    so the swap wall does not need to re-resolve the skeleton.
    """
    slide = _slide(deck, slot)
    return list((slide or {}).get("accepted_block_types") or [])


def gate_text(content: str, *, track: str | None) -> tuple[str, list]:
    """Run ``content`` through the gate; return ``(gate_id, findings)``.

    Mirrors the assembly engine's fail-closed contract: a non-pass verdict or an
    unreachable gate produces findings (which mark the deck un-sendable), never an
    exception that loses the edit. An empty body is a clean no-op.
    """
    if not content or not content.strip():
        return "", []
    try:
        result = check_gate(content, track=track or None, content_type="email")
    except GateError:
        return "", [{"rule": "gate_unreachable"}]
    gate_id = result.get("gate_id") or ""
    if result.get("verdict") != "pass":
        findings = result.get("findings") or [
            {"rule": "gate_non_pass", "verdict": result.get("verdict")}
        ]
        return gate_id, findings
    return gate_id, []


# -------------------------------------------------------------------------
# (1) Section request — deterministic SEAM for the agent-service edit pass
# -------------------------------------------------------------------------


def apply_section_request(deck: DeckRegistry, slide_index: int, instruction: str) -> dict | None:
    """Apply a free-text ``instruction`` to one slide's generated line. SEAM.

    # SEAM: real agent-service section-edit pass later.

    Returns the edited slide dict (already written into ``deck.slides_payload`` in
    memory — the caller persists + re-gates + versions), or ``None`` if the slide
    index is out of range. Today the edit is deterministic: the instruction's
    intent is folded into the slide's ``personalization`` line and the slide is
    flagged ``edited`` so the change is observable. Only the GENERATED layer is
    touched — pre-approved block ``content_md`` is left intact.
    """
    slide = _slide(deck, slide_index)
    if slide is None:
        return None
    instruction = (instruction or "").strip()
    base = slide.get("personalization") or slide.get("content_md") or ""
    # Deterministic stand-in for the real edit pass: re-state the line with the
    # requested intent appended, then run it through the voice SEAM (identity now).
    edited_line = apply_voice(f"{base} — {instruction}".strip(" —") if instruction else base)
    slide["personalization"] = edited_line
    slide["edited"] = True
    deck.slides_payload[slide_index] = slide
    return slide


# -------------------------------------------------------------------------
# (2) Block swap — walled browse + swap
# -------------------------------------------------------------------------


def compatible_blocks(deck: DeckRegistry, slot: int):
    """The live blocks that may fill ``slot`` — the SAME wall assembly enforces.

    Filtered by the slot's ``accepted_block_types`` + the skeleton audience +
    confirmed ONLY, then the thread track + sensitivity ceiling. Returns a list of
    :class:`~apps.decks.models.Block` (newest version first) Joseph can swap in.
    """
    from apps.decks.assembly import _SKELETON_AUDIENCE

    accepted = _slot_accepted_types(deck, slot)
    if not accepted:
        return []
    audience = _SKELETON_AUDIENCE.get(deck.skeleton_id, Block.Audience.INTERNAL)
    track = _thread_track(deck)
    ceiling = _thread_sensitivity_ceiling(deck)

    qs = Block.objects.filter(
        audience_type=audience,
        confirmation_status=Block.Confirmation.CONFIRMED,
        type__in=accepted,
        superseded_by__isnull=True,
    ).order_by("type", "-version")
    out = []
    for b in qs:
        if _SENSITIVITY_RANK.get(b.sensitivity, 99) > ceiling:
            continue
        if track and track not in b.tracks:
            continue
        out.append(b)
    return out


def swap_block(deck: DeckRegistry, slot: int, block_id: str) -> Block:
    """Swap ``block_id`` into ``slot`` — rebuilding that slide's content. In-memory.

    Validates the block against the slot wall (:class:`SwapRejected` if it fails),
    then repoints ``deck.block_versions[slot]`` and rebuilds the slide's pinned
    ``content_md`` + ``block_ids`` + ``citations``. The caller persists + re-gates
    + versions.
    """
    candidates = {str(b.id): b for b in compatible_blocks(deck, slot)}
    block = candidates.get(str(block_id))
    if block is None:
        raise SwapRejected(
            f"block {block_id} is not compatible with slot {slot} "
            f"(accepted={_slot_accepted_types(deck, slot)}, track={_thread_track(deck)!r})"
        )

    # Repoint the registry's per-slot block versions.
    deck.block_versions = dict(deck.block_versions or {})
    deck.block_versions[str(slot)] = [str(block.id)]

    # Rebuild the targeted slide's pinned content (the generated personalization
    # line is left as-is — a swap changes the *fact*, not the framing).
    slide = _slide(deck, slot)
    if slide is not None:
        slide["block_ids"] = [str(block.id)]
        slide["content_md"] = block.content_md
        cite = list(slide.get("citations") or [])
        new_cites = [c for c in ([block.source_ref] if block.source_ref else []) + [str(block.id)]]
        slide["citations"] = new_cites + [c for c in cite if c not in new_cites]
        slide["edited"] = True
        deck.slides_payload[slot] = slide
    return block


# -------------------------------------------------------------------------
# (3) Direct edit + sync — pull live Slides state back in
# -------------------------------------------------------------------------


def pull_slides_state(deck: DeckRegistry) -> list[dict]:
    """Pull the live Google Slides state back into the structured payload. SEAM.

    # SEAM: real Google Slides presentations.get later.

    Today it degrades to the deck's current ``slides_payload`` (there is no live
    presentation yet), so ``sync`` is a deterministic, testable round-trip. When
    wired, the body reads the presentation by ``deck.slides_id`` and re-derives the
    structured payload from the live slides (so Joseph's direct in-Slides edits are
    pulled back and re-gate-verified).
    """
    return deck.slides_payload or []


def gated_body(payload: list[dict]) -> str:
    """The generated-layer body a (re-)gate runs against — the personalization lines.

    Block ``content_md`` is pre-approved and never re-gated; only the generated
    personalization lines are concatenated into the gated body (mirrors assembly).
    """
    return "\n".join(
        (s.get("personalization") or "").strip()
        for s in (payload or [])
        if (s.get("personalization") or "").strip()
    )
