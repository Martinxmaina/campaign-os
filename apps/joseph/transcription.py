"""Transcription seam for the meeting-capture loop (TB.4, Task 5).

# SEAM: real Whisper / Google STT transcription wires in here later — this is a
# pure function with a stable shape (``transcribe(voice_note) -> str``) so the
# whole capture→extract loop is testable and shippable today; swapping in the
# real model is a one-function change with the tests already written.

For now it echoes a stored transcript override when one is present (the test/dev
path — a quick-form capture or a manually pasted transcript), else returns a
stable placeholder keyed off the note id so the downstream extraction seam has
deterministic input. It never calls an external model.
"""
from __future__ import annotations


def transcribe(voice_note) -> str:
    """Return the transcript for ``voice_note``.

    # SEAM: real Whisper/Google STT later. Today: any transcript already stored
    on the note wins (lets tests/dev seed deterministic input); otherwise a
    stable placeholder so the pipeline produces a consistent (empty-signal)
    extraction rather than crashing on a missing model.
    """
    stored = (getattr(voice_note, "transcript", "") or "").strip()
    if stored:
        return stored
    return f"[transcript pending for voice note {voice_note.id}]"
