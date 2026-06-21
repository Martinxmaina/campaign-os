"""Tests for the async meeting extraction pipeline (TB.4, Task 5).

The voice path of the capture surface (Task 4) persists a ``VoiceNote`` and
enqueues ``extract_meeting``; this is the async pipeline that chains the two
deterministic seams — ``transcription.transcribe`` then ``extraction.extract`` —
and persists the resulting ``ExtractedMeeting`` with its ``ExtractedItem``
children (state=pending) for the confirm screen (Task 6) to route.

Both seams are deterministic so the loop is fully testable today; the real
Whisper/Google-STT and agent-service ATLAS wiring is a one-function swap (the
SEAM markers live in ``transcription.py`` / ``extraction.py``).

- transcription seam: returns any stored transcript override (the test/dev path)
  else a stable placeholder for the fixture audio — never calls a real model.
- extraction seam: a deterministic heuristic mapping returning the stable dict
  (commitments / next_steps / intelligence_signals / content_ideas /
  warmth_delta / relationship_notes), so the shape + routing-set are exercised.
- ``extract_meeting(voice_note_id)``: uploaded → transcribing → transcribed →
  extracted, writes the transcript, builds the ExtractedMeeting + items; it is
  idempotent (a re-run never duplicates) and a failure sets status=failed
  without raising.
"""
import pytest
from django.utils import timezone

from apps.joseph.models import (
    ExtractedItem,
    ExtractedMeeting,
    VoiceNote,
)


# --------------------------------------------------------------------------
# helpers (reuse the established thread/voice-note pattern)
# --------------------------------------------------------------------------


def _thread(*, owner=None, org_name="Rockefeller Foundation", track="energy"):
    from apps.crm.models import Organization, OutreachThread

    org = Organization.objects.create(name=org_name)
    return OutreachThread.objects.create(org=org, track=track, owner=owner)


def _user():
    from apps.accounts.models import User

    return User.objects.create_user(
        email="capturer@example.com",
        password="x",
        name="Capturer",
        tos_accepted_at=timezone.now(),
    )


def _voice_note(thread, user, *, transcript=""):
    """A persisted VoiceNote (status uploaded). ``transcript`` seeds the seam's
    stored-transcript override so the pipeline produces deterministic items."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    return VoiceNote.objects.create(
        thread=thread,
        created_by=user,
        file=SimpleUploadedFile("note.m4a", b"FAKE-AUDIO-BYTES", content_type="audio/mp4"),
        status=VoiceNote.Status.UPLOADED,
        transcript=transcript,
    )


# A transcript with one signal per routing kind the extraction seam keys off.
_RICH = (
    "They committed to fund 2 million dollars over three years. "
    "Next step: I will send the concept note by Friday. "
    "She mentioned a new policy signal on the carbon market. "
    "We could turn this into a content idea about the energy transition."
)


# --------------------------------------------------------------------------
# transcription seam
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_transcribe_returns_stored_override_when_present():
    """The seam echoes a stored transcript (the test/dev path) — no real model."""
    from apps.joseph.transcription import transcribe

    user = _user()
    thread = _thread(owner=user)
    note = _voice_note(thread, user, transcript="pre-seeded transcript text")
    assert transcribe(note) == "pre-seeded transcript text"


@pytest.mark.django_db
def test_transcribe_is_deterministic_for_fixture_audio():
    """With no override the seam returns a stable, non-empty placeholder."""
    from apps.joseph.transcription import transcribe

    user = _user()
    thread = _thread(owner=user)
    note = _voice_note(thread, user)
    first = transcribe(note)
    second = transcribe(note)
    assert first == second
    assert first  # non-empty placeholder


# --------------------------------------------------------------------------
# extraction seam
# --------------------------------------------------------------------------


def test_extract_returns_stable_shape():
    """The extraction seam returns the agreed structured dict shape."""
    from apps.joseph.extraction import extract

    thread = None  # the seam tolerates a missing thread (shape only)
    result = extract("anything", thread)
    for key in (
        "commitments",
        "next_steps",
        "intelligence_signals",
        "content_ideas",
        "warmth_delta",
        "relationship_notes",
    ):
        assert key in result
    assert isinstance(result["commitments"], list)
    assert isinstance(result["next_steps"], list)
    assert isinstance(result["intelligence_signals"], list)
    assert isinstance(result["content_ideas"], list)


def test_extract_is_deterministic():
    from apps.joseph.extraction import extract

    assert extract(_RICH, None) == extract(_RICH, None)


def test_extract_maps_transcript_signals_to_routing_kinds():
    """The heuristic mapping surfaces a commitment, a next step, an intelligence
    signal and a content idea from a rich transcript, and a warmth read."""
    from apps.joseph.extraction import extract

    result = extract(_RICH, None)
    assert result["commitments"], "expected a commitment line"
    assert result["next_steps"], "expected a next-step line"
    assert result["intelligence_signals"], "expected an intelligence signal"
    assert result["content_ideas"], "expected a content idea"
    assert result["warmth_delta"] in (
        ExtractedMeeting.WarmthDelta.values + [""]
    )


# --------------------------------------------------------------------------
# extract_meeting task — the chained pipeline
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_extract_meeting_walks_status_and_builds_meeting():
    from apps.joseph.tasks import extract_meeting

    user = _user()
    thread = _thread(owner=user)
    note = _voice_note(thread, user, transcript=_RICH)

    extract_meeting(str(note.id))

    note.refresh_from_db()
    assert note.status == VoiceNote.Status.EXTRACTED
    assert note.transcript == _RICH

    meeting = ExtractedMeeting.objects.get(voice_note=note)
    assert meeting.thread_id == thread.id
    assert meeting.source == ExtractedMeeting.Source.VOICE
    assert meeting.status == ExtractedMeeting.Status.PENDING
    assert meeting.transcript == _RICH

    items = list(meeting.items.all())
    assert items, "expected extracted items"
    routing_kinds = set(ExtractedItem.Kind.values)
    for item in items:
        assert item.kind in routing_kinds
        assert item.state == ExtractedItem.State.PENDING


@pytest.mark.django_db
def test_extract_meeting_is_idempotent():
    from apps.joseph.tasks import extract_meeting

    user = _user()
    thread = _thread(owner=user)
    note = _voice_note(thread, user, transcript=_RICH)

    extract_meeting(str(note.id))
    first_count = ExtractedItem.objects.filter(meeting__voice_note=note).count()
    extract_meeting(str(note.id))
    second_count = ExtractedItem.objects.filter(meeting__voice_note=note).count()

    assert ExtractedMeeting.objects.filter(voice_note=note).count() == 1
    assert first_count == second_count


@pytest.mark.django_db
def test_extract_meeting_failure_sets_failed_without_raising():
    from apps.joseph.tasks import extract_meeting

    user = _user()
    thread = _thread(owner=user)
    note = _voice_note(thread, user, transcript=_RICH)

    from unittest.mock import patch

    with patch("apps.joseph.tasks.transcribe", side_effect=RuntimeError("boom")):
        # must not raise — the failure path marks the note failed
        result = extract_meeting(str(note.id))

    note.refresh_from_db()
    assert note.status == VoiceNote.Status.FAILED
    assert not ExtractedMeeting.objects.filter(voice_note=note).exists()
    assert result.get("status") == "failed"


@pytest.mark.django_db
def test_extract_meeting_missing_note_is_noop():
    """A vanished voice-note id never raises (returns a skip summary)."""
    import uuid

    from apps.joseph.tasks import extract_meeting

    result = extract_meeting(str(uuid.uuid4()))
    assert result.get("skipped")
