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

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.decks.models import Block, DeckRegistry, DeckVersion, record_version
from apps.joseph.views import _can_access_joseph


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

    return render(
        request,
        "decks/review.html",
        {
            "deck": deck,
            "versions": versions,
            "block_rows": block_rows,
            "slides": deck.slides_payload or [],
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
