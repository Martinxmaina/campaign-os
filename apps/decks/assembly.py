"""Deck assembly engine (TB.5 Task 2) — ``assemble_deck``.

The engine turns a *thread* + an *audience skeleton* into a gate-verified,
source-cited ``DeckRegistry`` row. It is the walled chokepoint of the module:

1. **Dossier** — load L2-preferred / L1-fallback context; if neither exists,
   ``compile_dossier`` then proceed with whatever comes back (degrade, never
   block).
2. **Walled selection** — candidate blocks are filtered to the skeleton's
   ``audience_type``, ``confirmation_status=confirmed`` ONLY, and
   ``sensitivity <= thread sensitivity``. A confirmed candidate of the right
   audience+type whose **track does not match the thread** is a HARD
   :class:`DeckAssemblyError` naming the offending block id (the cross-track
   wall — never a silent skip). A *required* slot with no confirmed block is a
   HARD :class:`DeckAssemblyError` naming the exact slide + accepted field.
3. **Personalization** — a generated layer (opening framing from the dossier
   ``hook_by_track``, an audience→vocabulary map, the ask line from track +
   ``ask_amount``) is run through ``apply_voice`` (SEAM) then ``check_gate``.
   A gate finding lands on the registry and marks the deck un-sendable but still
   reviewable. Every generated claim must cite a dossier source or a block id,
   else it is flagged ``untraceable``.
4. **Registry + render + notify** — a ``DeckRegistry`` row is written (block
   versions, slides payload, gate verdict, placeholder Slides handle), the
   render SEAM stamps ``slides_url``/``slides_id``, and ``notify(DECK_READY)``
   fires for the presenter.
"""
from __future__ import annotations

from apps.decks import skeletons
from apps.decks.continuity import apply_continuity
from apps.decks.models import Block, DeckRegistry
from apps.decks.slides import render as render_slides
from apps.decks.voice import apply_voice
from apps.joseph.readers import compile_dossier, get_dossier
from apps.notifications.engine import notify
from apps.notifications.models import EventType
from apps.publisher.gate_client import GateError, check_gate

# Sensitivity ordering — a block may assemble only when its level is <= the
# thread's level (public_safe < partner_only < confidential).
_SENSITIVITY_RANK = {
    Block.Sensitivity.PUBLIC_SAFE: 0,
    Block.Sensitivity.PARTNER_ONLY: 1,
    Block.Sensitivity.CONFIDENTIAL: 2,
}

# Tracks whose content is public-facing by default (mirrors joseph.routing).
_PUBLIC_SAFE_TRACKS = {"core", "programs"}

# skeleton_id → the audience_type its blocks must carry.
_SKELETON_AUDIENCE = {
    "philanthropy_anchor": Block.Audience.PHILANTHROPY_ANCHOR,
    "bilateral_ta": Block.Audience.BILATERAL_TA,
    "corporate_sponsor": Block.Audience.CORPORATE_SPONSOR,
    "dfi": Block.Audience.DFI,
    "principal_brief": Block.Audience.INTERNAL,
}

# audience_type → the vocabulary the personalization layer leans into.
_AUDIENCE_VOCABULARY = {
    Block.Audience.PHILANTHROPY_ANCHOR: "catalytic capital",
    Block.Audience.BILATERAL_TA: "digital public infrastructure",
    Block.Audience.CORPORATE_SPONSOR: "energy-compute nexus",
    Block.Audience.DFI: "blended finance architecture",
    Block.Audience.INTERNAL: "the principal brief",
}


class DeckAssemblyError(Exception):
    """A hard wall breach — a cross-track block or an empty required slot.

    Never a warning: assembly stops and the message names the offending block id
    (cross-track) or the exact slide + accepted field (empty required slot).
    """


def _thread_sensitivity(thread) -> str:
    """The thread's sensitivity ceiling.

    A ``restricted`` thread can carry confidential blocks; otherwise the ceiling
    is inferred from the track (public tracks → public_safe, else partner_only),
    mirroring ``joseph.routing._infer_sensitivity`` (fail-closed: unknown →
    partner_only).
    """
    if getattr(thread, "restricted", False):
        return Block.Sensitivity.CONFIDENTIAL
    track = (getattr(thread, "track", "") or "").strip().lower()
    if track in _PUBLIC_SAFE_TRACKS:
        return Block.Sensitivity.PUBLIC_SAFE
    return Block.Sensitivity.PARTNER_ONLY


def _load_dossier(thread) -> dict:
    """L2-preferred / L1-fallback dossier load; compile then proceed if neither.

    Returns whatever context is available (possibly ``{}``) — a missing dossier
    degrades to an empty personalization context, it never blocks assembly.
    """
    dossier_id = getattr(thread, "dossier_id", "") or ""
    if dossier_id:
        dossier = get_dossier(dossier_id) or {}
        if dossier:
            return dossier
    # No dossier on the thread (or it read back empty) → trigger a compile and
    # proceed with whatever comes back.
    return compile_dossier(str(thread.id)) or {}


def _hook_for_track(dossier: dict, track: str) -> str:
    """Opening framing — the dossier ``hook_by_track`` entry (then ``hooks``)."""
    by_track = dossier.get("hook_by_track") or dossier.get("hooks") or {}
    if track and by_track.get(track):
        return by_track[track]
    # any hook is better than none for the opening framing
    return next(iter(by_track.values()), "") if by_track else ""


def _select_blocks(skeleton: dict, *, audience: str, track: str, sensitivity_ceiling: str) -> dict:
    """Walled per-slot selection. Returns ``{slot_index: [Block, ...]}``.

    Raises :class:`DeckAssemblyError` for a cross-track candidate (HARD) or an
    empty *required* slot (HARD, naming slide + field).
    """
    ceiling = _SENSITIVITY_RANK[sensitivity_ceiling]
    selected: dict[int, list[Block]] = {}

    for idx, slot in enumerate(skeleton["slide_order"]):
        accepted = slot["accepted_block_types"]
        # Candidate set for THIS slot: right audience, confirmed only, accepted
        # type, sensitivity within the thread ceiling. Track is checked next so a
        # cross-track candidate raises rather than being silently dropped.
        candidates = list(
            Block.objects.filter(
                audience_type=audience,
                confirmation_status=Block.Confirmation.CONFIRMED,
                type__in=accepted,
            ).order_by("type", "-version")
        )
        candidates = [b for b in candidates if _SENSITIVITY_RANK.get(b.sensitivity, 99) <= ceiling]

        # Cross-track wall: a confirmed, in-audience, in-sensitivity candidate
        # whose track does not include the thread track is a HARD error.
        for b in candidates:
            if track and track not in b.tracks:
                raise DeckAssemblyError(
                    f"cross-track wall: block {b.id} (track={b.tracks}) cannot assemble "
                    f"into a {track!r} deck (slide {idx}, accepted={accepted})"
                )

        chosen = candidates[: slot.get("max_blocks", 1)]
        if slot.get("required", True) and not chosen:
            raise DeckAssemblyError(
                f"required slot {idx} (field/accepted_block_types={accepted}) has no "
                f"confirmed block for audience={audience}, track={track!r}"
            )
        selected[idx] = chosen
    return selected


def _build_payload(
    skeleton: dict,
    selected: dict,
    *,
    dossier: dict,
    audience: str,
    track: str,
    ask_amount: str | None,
) -> tuple[list[dict], list[str]]:
    """Build the per-slide payload + the list of generated (personalization) lines.

    Each slide carries its block content (pre-approved, never voiced), a generated
    ``personalization`` line, and the ``citations`` that ground it. A generated
    line with zero citations is flagged ``untraceable`` (recorded on the slide).
    The second return value is the concatenation of generated lines that must be
    voiced + gated as one body.
    """
    hook = _hook_for_track(dossier, track)
    vocab = _AUDIENCE_VOCABULARY.get(audience, "")
    sources = dossier.get("sources") or []
    source_ids = [str(s.get("id")) for s in sources if isinstance(s, dict) and s.get("id")]

    payload: list[dict] = []
    generated_lines: list[str] = []

    for idx, slot in enumerate(skeleton["slide_order"]):
        blocks = selected.get(idx, [])
        block_ids = [str(b.id) for b in blocks]
        block_source_refs = [b.source_ref for b in blocks if b.source_ref]
        # Slide-level citations (what the review screen shows): every block's
        # source_ref + the block ids + the dossier sources.
        citations = block_source_refs + block_ids + source_ids

        # The generated personalization line for this slide. A generated claim is
        # only as traceable as the *provenance* it draws on: dossier sources or
        # the block source_refs it personalizes — a bare block id grounds the
        # block's pre-approved content, not the generated line.
        gen_provenance = source_ids + block_source_refs

        is_opening = idx == 0
        is_ask = "ask" in slot["accepted_block_types"]
        personalization = ""
        if is_opening:
            framing = hook or "Africa is the platform for the AI decade."
            personalization = f"{framing} ({vocab})." if vocab else framing
        elif is_ask:
            amount = f" — {ask_amount}" if ask_amount else ""
            personalization = (
                f"The ask, framed through {vocab}{amount}." if vocab else f"The ask{amount}."
            )
        elif vocab and blocks:
            personalization = f"Framed for {vocab}."

        slide = {
            "slide": idx,
            "accepted_block_types": slot["accepted_block_types"],
            "block_ids": block_ids,
            "content_md": "\n\n".join(b.content_md for b in blocks),
            "personalization": personalization,
            "citations": citations,
        }
        if personalization:
            generated_lines.append(personalization)
            # Traceability: a generated claim must cite a dossier source or a
            # block source_ref, else it is flagged untraceable (still surfaced,
            # never dropped — Joseph reviews it).
            if not gen_provenance:
                slide["untraceable"] = True
                slide["personalization"] = f"{personalization} [untraceable]"
        payload.append(slide)

    return payload, generated_lines


def assemble_deck(thread, skeleton_id: str, ask_amount: str | None = None, presenter=None) -> DeckRegistry:
    """Assemble a gate-verified, source-cited deck for ``thread``.

    See the module docstring for the full pipeline. Returns the persisted
    ``DeckRegistry`` (status=draft). Raises :class:`DeckAssemblyError` on a
    cross-track wall breach or an empty required slot.
    """
    skeleton = skeletons.get(skeleton_id)
    if skeleton is None:
        raise DeckAssemblyError(f"unknown skeleton {skeleton_id!r}")

    audience = _SKELETON_AUDIENCE.get(skeleton_id, Block.Audience.INTERNAL)
    track = (getattr(thread, "track", "") or "").strip()
    sensitivity_ceiling = _thread_sensitivity(thread)

    # 1. dossier
    dossier = _load_dossier(thread)

    # 2. walled selection (raises on cross-track / empty required slot)
    selected = _select_blocks(
        skeleton, audience=audience, track=track, sensitivity_ceiling=sensitivity_ceiling
    )

    # 3. personalization → voice SEAM → gate
    payload, generated_lines = _build_payload(
        skeleton, selected, dossier=dossier, audience=audience, track=track, ask_amount=ask_amount
    )

    # 3b. continuity — a follow-up to a prior SENT deck is a delta (drop repeats,
    # add a "Progress since" slide, note stage/dossier diffs), not a re-pitch.
    payload, change_summary, is_continuation = apply_continuity(
        thread, payload=payload, dossier=dossier
    )

    voiced = "\n".join(apply_voice(line) for line in generated_lines)
    gate_id = ""
    findings: list = []
    if voiced.strip():
        try:
            result = check_gate(voiced, track=track or None, content_type="email")
        except GateError:
            # Gate unreachable → fail closed: no verdict id, flag for review.
            result = {"verdict": "error", "findings": [{"rule": "gate_unreachable"}], "gate_id": ""}
        gate_id = result.get("gate_id") or ""
        if result.get("verdict") != "pass":
            findings = result.get("findings") or [{"rule": "gate_non_pass", "verdict": result.get("verdict")}]

    # block_versions: {slot_index: [block_id, ...]}
    block_versions = {str(idx): [str(b.id) for b in blocks] for idx, blocks in selected.items()}

    # 4. registry row + render SEAM + notify
    deck = DeckRegistry.objects.create(
        thread=thread,
        skeleton_id=skeleton_id,
        block_versions=block_versions,
        slides_payload=payload,
        presenter=presenter,
        ask_amount=ask_amount or "",
        thread_stage=(getattr(thread, "stage", "") or ""),
        dossier_updated_at=str(dossier.get("updated_at") or ""),
        gate_id=gate_id,
        findings=findings,
        status=DeckRegistry.Status.DRAFT,
        is_continuation=is_continuation,
        change_summary=change_summary,
    )

    rendered = render_slides(deck)
    deck.slides_url = rendered.get("slides_url", "")
    deck.slides_id = rendered.get("slides_id", "")
    deck.save(update_fields=["slides_url", "slides_id", "updated_at"])

    if presenter is not None:
        org_name = thread.org.name if getattr(thread, "org_id", None) else "a thread"
        notify(
            user=presenter,
            event_type=EventType.DECK_READY,
            title=f"Deck ready: {org_name}",
            body=(
                f"A {skeleton_id} deck is assembled and ready to review"
                + (" (gate flagged — review before sending)." if findings else ".")
            ),
            data={"deck_id": str(deck.id), "thread_id": str(thread.id), "sendable": deck.is_sendable},
        )

    return deck
