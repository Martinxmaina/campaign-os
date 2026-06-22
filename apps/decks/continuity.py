"""Deck continuity (TB.5 Task 4) — a follow-up deck is a *delta*, not a re-pitch.

When a thread already has a **sent** deck, assembling its next deck should not put
the same slides in front of the funder again. ``apply_continuity`` turns a freshly
built payload into a continuation:

  - **Drop the repeats** — any content slide whose blocks were *all* in the prior
    sent deck is dropped; the ``change_summary`` records what was dropped and what
    is new (so the review screen can show the "what changed").
  - **Progress slide** — a generated "Progress since <date>" slide is inserted,
    populated from the :class:`~apps.crm.models.Activity` rows
    (commitments / meetings / milestones) booked since the prior deck. Joseph
    reviews it (the deck stays a draft).
  - **Ask update** — when the thread ``stage`` advanced since the prior deck, the
    advance is noted on the summary (the ask line itself is already re-generated
    from the live track + ``ask_amount`` by the base engine).
  - **Dossier diff** — a changed dossier ``updated_at`` is noted as a funder update.

``skeleton_for_thread`` is the default-skeleton resolver the proactive T-5 hook
uses: it maps the organisation type (then the track) to the right audience
skeleton so an auto-assembled deck targets the correct audience.
"""
from __future__ import annotations

from apps.decks.models import DeckRegistry

# Activity types that count as "progress" worth surfacing on the progress slide.
_PROGRESS_ACTIVITY_TYPES = {
    "meeting",
    "commitment_recorded",
    "stage_advanced",
    "milestone",
    "call",
    "email_reply",
}

# Org type → default audience skeleton (the proactive T-5 trigger's resolver).
_ORG_TYPE_SKELETON = {
    "funder": "philanthropy_anchor",
    "bilateral": "bilateral_ta",
    "dfi": "dfi",
    "corporate": "corporate_sponsor",
    "government": "bilateral_ta",
    "partner": "corporate_sponsor",
}

# Track → fallback skeleton when the org type is unset/unknown.
_TRACK_SKELETON = {
    "ai10bn": "philanthropy_anchor",
    "waiis": "dfi",
    "programs": "bilateral_ta",
    "core": "philanthropy_anchor",
}


def skeleton_for_thread(thread) -> str:
    """The default audience skeleton for ``thread`` (org type, then track).

    Used by the proactive T-5 hook so an auto-assembled deck targets the right
    audience. Falls back to ``principal_brief`` (the internal read) when neither
    the org type nor the track is recognised — never raises.
    """
    org_type = (getattr(getattr(thread, "org", None), "type", "") or "").strip().lower()
    if org_type in _ORG_TYPE_SKELETON:
        return _ORG_TYPE_SKELETON[org_type]
    track = (getattr(thread, "track", "") or "").strip().lower()
    return _TRACK_SKELETON.get(track, "principal_brief")


def latest_sent_deck(thread) -> DeckRegistry | None:
    """The most recent SENT deck for ``thread`` (the continuity baseline), or None."""
    return (
        DeckRegistry.objects.filter(thread=thread, status=DeckRegistry.Status.SENT)
        .order_by("-created_at")
        .first()
    )


def _prior_block_ids(prior: DeckRegistry) -> set[str]:
    return {b for ids in (prior.block_versions or {}).values() for b in ids}


def _progress_slide(thread, since) -> dict | None:
    """A generated "Progress since <date>" slide from Activity rows since ``since``.

    Returns ``None`` when nothing of note happened (so an empty progress slide is
    never inserted). Only the human-meaningful activity types are surfaced.
    """
    from apps.crm.models import Activity

    rows = (
        Activity.objects.filter(thread=thread, created_at__gt=since)
        .order_by("created_at")
    )
    items: list[str] = []
    for a in rows:
        if a.activity_type not in _PROGRESS_ACTIVITY_TYPES:
            continue
        ref = a.content_ref or {}
        summary = (ref.get("summary") or ref.get("note") or "").strip()
        label = a.activity_type.replace("_", " ")
        items.append(f"{label}: {summary}" if summary else label)
    if not items:
        return None
    since_label = since.date().isoformat() if hasattr(since, "date") else str(since)
    return {
        "slide": None,  # positional index is fixed up by the caller
        "kind": "progress",
        "title": f"Progress since {since_label}",
        "accepted_block_types": [],
        "block_ids": [],
        "content_md": "Since the last deck:",
        "items": items,
        "personalization": "",
        "citations": [f"activities:{thread.id}"],
    }


def apply_continuity(thread, *, payload: list[dict], dossier: dict) -> tuple[list[dict], dict, bool]:
    """Turn a freshly-built ``payload`` into a continuation of the prior SENT deck.

    Returns ``(payload, change_summary, is_continuation)``. With no prior *sent*
    deck the payload is returned untouched (``is_continuation=False``,
    ``change_summary={}``) — only a deck that actually went out establishes a
    baseline to diff against.
    """
    prior = latest_sent_deck(thread)
    if prior is None:
        return payload, {}, False

    prior_ids = _prior_block_ids(prior)

    kept: list[dict] = []
    dropped: list[int] = []
    new: list[int] = []
    for slide in payload:
        block_ids = slide.get("block_ids") or []
        is_ask = "ask" in (slide.get("accepted_block_types") or [])
        # The ask slide always survives — its generated line tracks the live
        # ask_amount + stage, so it is re-stated (updated) on every follow-up even
        # when the underlying block is unchanged.
        if is_ask:
            kept.append(slide)
            continue
        # A content slide whose every block was already in the prior deck is a
        # repeat → drop it (the funder has seen it). Slides with no blocks (pure
        # generated framing) are always kept.
        if block_ids and all(b in prior_ids for b in block_ids):
            dropped.append(slide.get("slide"))
            continue
        if block_ids and any(b not in prior_ids for b in block_ids):
            new.append(slide.get("slide"))
        kept.append(slide)

    # Insert the "Progress since <date>" slide (from Activity rows) right after the
    # opening framing slide, so the funder sees momentum before the (new) content.
    progress = _progress_slide(thread, prior.created_at)
    if progress is not None:
        insert_at = 1 if kept else 0
        kept.insert(insert_at, progress)

    # Re-number the surviving slides so the payload stays positionally consistent.
    for i, slide in enumerate(kept):
        slide["slide"] = i

    # Stage advance + dossier diff notes.
    stage_advanced = ""
    cur_stage = (getattr(thread, "stage", "") or "").strip()
    if prior.thread_stage and cur_stage and cur_stage != prior.thread_stage:
        stage_advanced = f"{prior.thread_stage} → {cur_stage}"

    dossier_updated = ""
    cur_dossier_at = str((dossier or {}).get("updated_at") or "")
    if prior.dossier_updated_at and cur_dossier_at and cur_dossier_at != prior.dossier_updated_at:
        dossier_updated = cur_dossier_at

    change_summary = {
        "prior_deck_id": str(prior.id),
        "since": prior.created_at.isoformat(),
        "dropped": dropped,
        "new": new,
        "progress_added": progress is not None,
        "stage_advanced": stage_advanced,
        "dossier_updated": dossier_updated,
    }
    return kept, change_summary, True
