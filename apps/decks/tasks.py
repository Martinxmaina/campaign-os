"""Celery tasks for the deck module (TB.5).

``assemble_deck_task`` is the enqueueable wrapper around
:func:`apps.decks.assembly.assemble_deck` — the proactive T-5 pre-meeting hook
(Task 4) enqueues it so a deck assembles off the request path. The heavy work
(dossier read + gate) lives behind ``assemble_deck``; nothing heavy is imported
at module load.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.decks.tasks.assemble_deck_task", bind=True, max_retries=3, default_retry_delay=120)
def assemble_deck_task(self, thread_id: str, skeleton_id: str, ask_amount: str | None = None,
                       presenter_id=None) -> str | None:
    """Assemble a deck for ``thread_id`` off the request path. Returns the deck id.

    Resolves the thread + presenter locally, then delegates to
    :func:`apps.decks.assembly.assemble_deck`. A cross-track/empty-required-slot
    breach (``DeckAssemblyError``) is logged and swallowed (the deck simply is
    not produced) — the wall is a hard stop, not a retryable transport error.
    """
    from apps.accounts.models import User
    from apps.crm.models import OutreachThread
    from apps.decks.assembly import DeckAssemblyError, assemble_deck

    thread = OutreachThread.objects.filter(pk=thread_id).select_related("org").first()
    if thread is None:
        logger.warning("decks.assemble_deck_task: thread %s not found", thread_id)
        return None
    presenter = User.objects.filter(pk=presenter_id).first() if presenter_id else None

    try:
        deck = assemble_deck(thread, skeleton_id, ask_amount=ask_amount, presenter=presenter)
    except DeckAssemblyError as exc:
        logger.warning("decks.assemble_deck_task: assembly wall for thread %s: %s", thread_id, exc)
        return None
    logger.info("decks.assemble_deck_task: assembled deck %s for thread %s", deck.id, thread_id)
    return str(deck.id)
