"""Tests for the meeting-capture data model (TB.4).

The post-meeting loop persists four Django-side models:

- ``VoiceNote`` -- an uploaded audio file (configured storage = R2 in prod, FS in
  test) tied to a CRM thread + optional CalendarEvent, walking a transcription
  status machine (``uploaded -> transcribing -> transcribed -> extracted | failed``).
- ``ExtractedMeeting`` -- the structured outcome of one meeting (from a voice note
  or the quick form), carrying the transcript, a warmth delta, free-text
  relationship notes and a ``pending -> confirmed`` status.
- ``ExtractedItem`` -- one accept/edit/dismiss line of an ExtractedMeeting, whose
  ``kind`` is drawn from the routing set the confirm screen (Task 6) dispatches on.
- ``WikiRevisionCandidate`` -- a *proposed* (never auto-applied) wiki edit signal
  surfaced from a meeting, awaiting human review.
"""
from datetime import date, timedelta

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.joseph.models import (
    CalendarEvent,
    ExtractedItem,
    ExtractedMeeting,
    VoiceNote,
    WikiRevisionCandidate,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _thread(*, org_name="Rockefeller Foundation"):
    """Create a CRM OutreachThread (+ org)."""
    from apps.crm.models import Organization, OutreachThread

    org = Organization.objects.create(name=org_name)
    return OutreachThread.objects.create(org=org), org


# --------------------------------------------------------------------------
# VoiceNote
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_voice_note_round_trip_defaults_and_storage(user):
    thread, _ = _thread()
    vn = VoiceNote.objects.create(
        thread=thread,
        file=SimpleUploadedFile("note.m4a", b"fake-audio-bytes", content_type="audio/m4a"),
        created_by=user,
    )
    fetched = VoiceNote.objects.get(pk=vn.pk)
    # status defaults to "uploaded"; transcript empty; calendar_event optional
    assert fetched.status == VoiceNote.Status.UPLOADED == "uploaded"
    assert fetched.transcript == ""
    assert fetched.calendar_event is None
    assert fetched.created_by_id == user.id
    # the FileField uses the configured (default) storage -- the bytes are there
    assert default_storage.exists(fetched.file.name)
    assert fetched.file.read() == b"fake-audio-bytes"


@pytest.mark.django_db
def test_voice_note_status_choices_and_calendar_event(user, workspace):
    thread, _ = _thread()
    ev = CalendarEvent.objects.create(
        workspace=workspace, google_event_id="vn-ev", title="Sync", start=timezone.now()
    )
    vn = VoiceNote.objects.create(
        thread=thread,
        calendar_event=ev,
        file=SimpleUploadedFile("n.m4a", b"x"),
        status=VoiceNote.Status.TRANSCRIBED,
        transcript="they committed to 2 million",
        created_by=user,
    )
    fetched = VoiceNote.objects.get(pk=vn.pk)
    assert fetched.calendar_event_id == ev.id
    assert fetched.status == "transcribed"
    assert fetched.transcript == "they committed to 2 million"
    # the full status machine is available
    statuses = {c[0] for c in VoiceNote.Status.choices}
    assert statuses == {"uploaded", "transcribing", "transcribed", "extracted", "failed"}


# --------------------------------------------------------------------------
# ExtractedMeeting + ExtractedItem
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_extracted_meeting_defaults_and_relations(user):
    thread, _ = _thread()
    vn = VoiceNote.objects.create(
        thread=thread, file=SimpleUploadedFile("n.m4a", b"x"), created_by=user
    )
    em = ExtractedMeeting.objects.create(
        thread=thread,
        voice_note=vn,
        source=ExtractedMeeting.Source.VOICE,
        transcript="full transcript here",
    )
    fetched = ExtractedMeeting.objects.get(pk=em.pk)
    assert fetched.source == "voice"
    assert fetched.status == ExtractedMeeting.Status.PENDING == "pending"
    # warmth_delta is nullable (no signal yet); relationship_notes empty
    assert fetched.warmth_delta == ""
    assert fetched.relationship_notes == ""
    assert fetched.voice_note_id == vn.id
    # reverse accessor from the voice note
    assert vn.extracted_meetings.count() == 1


@pytest.mark.django_db
def test_extracted_meeting_form_source_no_voice_note_and_warmth_choices():
    thread, _ = _thread()
    em = ExtractedMeeting.objects.create(
        thread=thread,
        source=ExtractedMeeting.Source.FORM,
        warmth_delta=ExtractedMeeting.WarmthDelta.WARMER,
        relationship_notes="very engaged, asked to meet again",
    )
    fetched = ExtractedMeeting.objects.get(pk=em.pk)
    assert fetched.source == "form"
    assert fetched.voice_note is None
    assert fetched.warmth_delta == "warmer"
    deltas = {c[0] for c in ExtractedMeeting.WarmthDelta.choices}
    assert deltas == {"warmer", "same", "cooler"}
    sources = {c[0] for c in ExtractedMeeting.Source.choices}
    assert sources == {"voice", "form"}


@pytest.mark.django_db
def test_extracted_item_full_shape_and_kind_set(user):
    thread, _ = _thread()
    em = ExtractedMeeting.objects.create(thread=thread, source=ExtractedMeeting.Source.FORM)
    item = ExtractedItem.objects.create(
        meeting=em,
        kind=ExtractedItem.Kind.COMMITMENT_FINANCIAL,
        description="Committed to a USD 2M anchor grant",
        confidence=0.82,
        verbatim_quote="we can do two million",
        proposed_due=date.today() + timedelta(days=7),
        proposed_owner=user,
        wiki_update_candidate=False,
        payload={"amount": "2M"},
    )
    fetched = ExtractedItem.objects.get(pk=item.pk)
    assert fetched.kind == "commitment_financial"
    assert fetched.description == "Committed to a USD 2M anchor grant"
    assert fetched.confidence == pytest.approx(0.82)
    assert fetched.verbatim_quote == "we can do two million"
    assert fetched.proposed_owner_id == user.id
    assert fetched.wiki_update_candidate is False
    assert fetched.payload == {"amount": "2M"}
    # state defaults to pending
    assert fetched.state == ExtractedItem.State.PENDING == "pending"
    # reverse accessor from the meeting
    assert em.items.count() == 1
    # the routing kind set matches the plan exactly
    kinds = {c[0] for c in ExtractedItem.Kind.choices}
    assert kinds == {
        "commitment_financial",
        "commitment_intro",
        "commitment_follow_up",
        "interest_expressed",
        "objection_raised",
        "strategy_signal",
        "intelligence_signal",
        "next_step",
        "content_idea",
    }
    states = {c[0] for c in ExtractedItem.State.choices}
    assert states == {"pending", "accepted", "edited", "dismissed"}


@pytest.mark.django_db
def test_extracted_item_defaults_minimal():
    thread, _ = _thread()
    em = ExtractedMeeting.objects.create(thread=thread, source=ExtractedMeeting.Source.FORM)
    item = ExtractedItem.objects.create(
        meeting=em, kind=ExtractedItem.Kind.NEXT_STEP, description="Send the data room link"
    )
    fetched = ExtractedItem.objects.get(pk=item.pk)
    assert fetched.confidence == 0.0
    assert fetched.verbatim_quote == ""
    assert fetched.proposed_due is None
    assert fetched.proposed_owner is None
    assert fetched.wiki_update_candidate is False
    assert fetched.payload == {}
    assert fetched.state == "pending"


# --------------------------------------------------------------------------
# WikiRevisionCandidate
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_wiki_revision_candidate_proposed_by_default_never_applied():
    thread, org = _thread()
    em = ExtractedMeeting.objects.create(thread=thread, source=ExtractedMeeting.Source.VOICE)
    wrc = WikiRevisionCandidate.objects.create(
        org=org,
        thread=thread,
        source_meeting=em,
        signal="Officer is now the new programme lead for climate",
        proposed_change="Update org dossier: programme lead changed",
    )
    fetched = WikiRevisionCandidate.objects.get(pk=wrc.pk)
    # NEVER auto-applied -- proposed by default, awaiting human review
    assert fetched.status == WikiRevisionCandidate.Status.PROPOSED == "proposed"
    assert fetched.org_id == org.id
    assert fetched.thread_id == thread.id
    assert fetched.source_meeting_id == em.id
    assert fetched.signal.startswith("Officer is now")
    statuses = {c[0] for c in WikiRevisionCandidate.Status.choices}
    assert statuses == {"proposed", "applied", "dismissed"}
    # reverse accessor from the meeting
    assert em.wiki_revision_candidates.count() == 1
