"""Deck review surface (TB.5 Task 3).

Joseph's window onto an assembled deck and its history:

  * :func:`index` — the decks index (Joseph's action queue): draft decks first,
    then sent/archived, each linking into the review screen.
  * :func:`review` — the per-deck review screen: a slide preview (the rendered
    payload / placeholder seam embed), the gate status + any flagged findings, the
    block list with citations, and a version-history rail.
  * :func:`revert` — restore a prior :class:`~apps.decks.models.DeckVersion` by
    writing a NEW version row (never in-place), so the lineage is preserved.
  * :func:`stale` — the stale-figure report: *sent* decks whose registry pins a
    block version the live library has since superseded (the offending block +
    deck), so a corrected figure in the library surfaces every deck still on the
    old number.

Every view is role-gated by the SAME ``apps.joseph.views._can_access_joseph``
gate (no parallel auth) and CSP-safe (the templates carry nonce'd scripts + no
inline handlers). No network: the render is the deterministic SEAM and the gate
is not re-run here.
"""
from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.decks import edits as deck_edits
from apps.decks.models import Block, DeckRegistry, DeckVersion, record_version
from apps.joseph.views import _can_access_joseph

logger = logging.getLogger("apps.decks")


@login_required
def index(request):
    """The decks index — Joseph's deck action queue (drafts first)."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Decks are not available for your role.")

    decks = list(
        DeckRegistry.objects.select_related("thread", "thread__org").order_by(
            "-created_at"
        )
    )
    drafts = [d for d in decks if d.status == DeckRegistry.Status.DRAFT]
    others = [d for d in decks if d.status != DeckRegistry.Status.DRAFT]
    return render(
        request,
        "decks/index.html",
        {"drafts": drafts, "others": others, "deck_count": len(decks)},
    )


@login_required
def review(request, deck_id):
    """The per-deck review screen — preview + gate + blocks + version rail."""
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Decks are not available for your role.")

    deck = get_object_or_404(
        DeckRegistry.objects.select_related("thread", "thread__org", "presenter"),
        id=deck_id,
    )
    versions = list(deck.versions.order_by("-number"))

    # Resolve the block ids the slides pin to live Block rows so the block list
    # can show content + citations + a "superseded" flag (drives the stale link).
    block_ids = {
        bid for ids in (deck.block_versions or {}).values() for bid in ids
    }
    blocks_by_id = {
        str(b.id): b
        for b in Block.objects.filter(id__in=block_ids).select_related("superseded_by")
    }
    block_rows = []
    for slot, ids in sorted((deck.block_versions or {}).items()):
        for bid in ids:
            b = blocks_by_id.get(str(bid))
            block_rows.append(
                {
                    "slot": slot,
                    "id": str(bid),
                    "type": b.type if b else "",
                    "content_md": b.content_md if b else "(block removed)",
                    "source_ref": b.source_ref if b else "",
                    "superseded": bool(b and b.superseded_by_id),
                }
            )

    # Per-slot swap candidates for the block-swap mode: for each slide that pins a
    # block, the live library blocks that pass the SAME wall (accepted type + track
    # + sensitivity + confirmed) so Joseph can browse a compatible swap-in.
    swap_slots = []
    for idx, _slide in enumerate(deck.slides_payload or []):
        candidates = deck_edits.compatible_blocks(deck, slot=idx)
        if candidates:
            swap_slots.append(
                {
                    "slot": idx,
                    "current": (deck.block_versions or {}).get(str(idx), []),
                    "candidates": candidates,
                }
            )

    return render(
        request,
        "decks/review.html",
        {
            "deck": deck,
            "versions": versions,
            "block_rows": block_rows,
            "slides": deck.slides_payload or [],
            "swap_slots": swap_slots,
        },
    )


@login_required
@require_POST
def revert(request, deck_id, version_id):
    """Restore ``version_id`` onto ``deck`` by appending a NEW version row.

    Revert is never in-place: we copy the chosen snapshot's ``block_versions`` +
    ``slides_payload`` + gate verdict onto the live deck, then ``record_version``
    so the restore itself is a new entry in the lineage (reason ``revert to vN``).
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Decks are not available for your role.")

    deck = get_object_or_404(DeckRegistry, id=deck_id)
    version = get_object_or_404(DeckVersion, id=version_id, deck=deck)

    deck.block_versions = version.block_versions
    deck.slides_payload = version.slides_payload
    deck.gate_id = version.gate_id
    deck.findings = version.findings
    deck.save(
        update_fields=["block_versions", "slides_payload", "gate_id", "findings", "updated_at"]
    )
    record_version(deck, reason=f"revert to v{version.number}", created_by=request.user)

    return redirect(reverse("decks:review", args=[deck.id]))


@login_required
def stale(request):
    """The stale-figure report — sent decks pinning a now-superseded block.

    For every *sent* deck, resolve the block ids its registry pinned and flag any
    whose ``superseded_by`` is now set in the live library. The offending block +
    the deck are listed so a corrected figure is chased down across every deck it
    still appears in.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Decks are not available for your role.")

    sent_decks = list(
        DeckRegistry.objects.filter(status=DeckRegistry.Status.SENT).select_related(
            "thread", "thread__org"
        )
    )

    # All block ids pinned by any sent deck → resolve once, find which are superseded.
    pinned_ids = {
        bid
        for d in sent_decks
        for ids in (d.block_versions or {}).values()
        for bid in ids
    }
    superseded = {
        str(b.id): b
        for b in Block.objects.filter(
            id__in=pinned_ids, superseded_by__isnull=False
        ).select_related("superseded_by")
    }

    rows = []
    for d in sent_decks:
        offenders = [
            {
                "block": superseded[str(bid)],
                "slot": slot,
                "current": superseded[str(bid)].superseded_by,
            }
            for slot, ids in (d.block_versions or {}).items()
            for bid in ids
            if str(bid) in superseded
        ]
        if offenders:
            rows.append({"deck": d, "offenders": offenders})

    return render(request, "decks/stale.html", {"rows": rows, "stale_count": len(rows)})


# -------------------------------------------------------------------------
# Customisation loop (TB.5 Task 5) — section request / block swap / sync.
# Each edit re-runs the gate (on the changed slide(s) for section/swap, on the
# whole deck for sync) and appends a DeckVersion so revert (Task 3) still works.
# -------------------------------------------------------------------------


def _persist_edit_gate(deck: DeckRegistry, *, gate_body: str, reason: str, user) -> None:
    """Re-gate ``gate_body``, write the verdict onto ``deck``, append a version.

    The single sanctioned path for an edit to land: it re-runs the gate (findings
    mark the deck un-sendable but never un-reviewable, mirroring assembly), saves
    the live payload + verdict, and records the new ``DeckVersion`` so the lineage
    holds across edits.
    """
    track = (getattr(deck.thread, "track", "") or "").strip()
    gate_id, findings = deck_edits.gate_text(gate_body, track=track)
    deck.gate_id = gate_id
    deck.findings = findings
    deck.save(
        update_fields=["block_versions", "slides_payload", "gate_id", "findings", "updated_at"]
    )
    record_version(deck, reason=reason, created_by=user)


@login_required
@require_POST
def edit_section(request, deck_id):
    """Section request — apply an NL instruction to one slide, re-gate it, version.

    SEAM-backed: ``edits.apply_section_request`` does the deterministic targeted
    edit (real agent-service section-edit pass later). Only the CHANGED slide's
    generated line is re-gated; the edit is audited (an episode line on
    ``apps.decks``).
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Decks are not available for your role.")

    deck = get_object_or_404(DeckRegistry, id=deck_id)
    try:
        slide_index = int(request.POST.get("slide", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("a numeric slide index is required")
    instruction = (request.POST.get("instruction") or "").strip()

    edited = deck_edits.apply_section_request(deck, slide_index, instruction)
    if edited is None:
        return HttpResponseBadRequest(f"slide {slide_index} is out of range")

    # Re-gate the CHANGED slide ONLY (its generated line), not the whole body.
    changed_line = (edited.get("personalization") or "").strip()
    _persist_edit_gate(
        deck,
        gate_body=changed_line,
        reason=f"section edit · slide {slide_index}",
        user=request.user,
    )
    logger.info(
        "deck section edit: deck=%s slide=%s by_user=%s (%s) instruction=%r",
        deck.id,
        slide_index,
        getattr(request.user, "id", None),
        getattr(request.user, "email", ""),
        instruction,
    )
    return redirect(reverse("decks:review", args=[deck.id]))


@login_required
@require_POST
def edit_swap(request, deck_id):
    """Block swap — swap a compatible block into a slot, re-gate that slide, version.

    The candidate is held to the SAME wall the assembly engine enforces (accepted
    type + track + sensitivity + confirmed). An incompatible block is rejected with
    400 (no swap, no version). The swapped slide's generated line is re-gated.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Decks are not available for your role.")

    deck = get_object_or_404(DeckRegistry, id=deck_id)
    try:
        slot = int(request.POST.get("slot", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("a numeric slot is required")
    block_id = (request.POST.get("block_id") or "").strip()

    try:
        deck_edits.swap_block(deck, slot, block_id)
    except deck_edits.SwapRejected as exc:
        return HttpResponseBadRequest(str(exc))

    slide = deck.slides_payload[slot] if 0 <= slot < len(deck.slides_payload) else {}
    changed_line = (slide.get("personalization") or "").strip()
    _persist_edit_gate(
        deck,
        gate_body=changed_line,
        reason=f"block swap · slot {slot}",
        user=request.user,
    )
    logger.info(
        "deck block swap: deck=%s slot=%s block=%s by_user=%s (%s)",
        deck.id,
        slot,
        block_id,
        getattr(request.user, "id", None),
        getattr(request.user, "email", ""),
    )
    return redirect(reverse("decks:review", args=[deck.id]))


@login_required
@require_POST
def sync(request, deck_id):
    """Direct edit + sync — pull live Slides state back in, re-gate the WHOLE deck.

    SEAM-backed: ``edits.pull_slides_state`` returns the live Slides payload (real
    presentations.get later; degrades to the current payload today). The whole
    deck's generated layer is re-gate-verified against the pulled state.
    """
    if not _can_access_joseph(request):
        return HttpResponseForbidden("Decks are not available for your role.")

    deck = get_object_or_404(DeckRegistry, id=deck_id)

    pulled = deck_edits.pull_slides_state(deck)
    deck.slides_payload = pulled
    _persist_edit_gate(
        deck,
        gate_body=deck_edits.gated_body(pulled),
        reason="direct-edit sync",
        user=request.user,
    )
    logger.info(
        "deck sync: deck=%s slides=%s by_user=%s (%s)",
        deck.id,
        deck.slides_id,
        getattr(request.user, "id", None),
        getattr(request.user, "email", ""),
    )
    return redirect(reverse("decks:review", args=[deck.id]))
