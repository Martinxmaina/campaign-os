"""Google Slides render SEAM (TB.5 Task 2).

# SEAM: real Google Slides API later.

``render(deck)`` is the one function that turns an assembled deck into a live
Google Slides presentation. Today it is a **deterministic placeholder** — it
returns a stable ``{slides_url, slides_id}`` derived from the deck so the whole
module (review screen, version history, continuity) is testable without Google
creds. When the creds land, the body of this function becomes the Slides
``presentations.create`` + ``batchUpdate`` (createSlide / insertText /
insertImage / updateCells) calls that materialise ``deck["slides_payload"]``;
the *signature* and its return contract do not change, so it is a one-function
swap with these tests already written.

It degrades gracefully: any failure returns an empty placeholder rather than
raising, so a render-layer outage never blocks the (already-gated, already-
persisted) deck from being reviewed.
"""
from __future__ import annotations

import uuid


def render(deck) -> dict:
    """Render ``deck`` to a Slides presentation. Returns ``{slides_url, slides_id}``.

    ``deck`` is a ``DeckRegistry`` instance OR a plain dict carrying a
    ``slides_payload`` — so the engine can render before the row is saved and the
    review screen can re-render an existing row. Deterministic placeholder until
    the real API lands.
    """
    try:
        deck_id = getattr(deck, "id", None) or (deck.get("id") if isinstance(deck, dict) else None)
        slides_id = f"slides-{deck_id or uuid.uuid4()}"
        # A stable placeholder embed URL; swapped for the real presentation URL
        # once Slides batchUpdate runs against deck["slides_payload"].
        slides_url = f"https://docs.google.com/presentation/d/{slides_id}/edit"
        return {"slides_url": slides_url, "slides_id": slides_id}
    except Exception:  # render is best-effort; never block the deck on the seam
        return {"slides_url": "", "slides_id": ""}
