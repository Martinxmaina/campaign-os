"""Tests for the post-meeting capture surface (TB.4).

The capture surface at ``/joseph/capture/<thread_id>/`` is the "I'm going in"
follow-up: after a meeting Joseph captures the outcome via one of three paths —
record a voice note, fill a quick 5-field form, or defer for later. A voice
upload creates a ``VoiceNote`` (status uploaded) and enqueues the async
extraction pipeline (Task 5); a form post creates an ``ExtractedMeeting``
(source=form, pending) with items derived directly from the 5 fields (no
transcription); a defer marks the event ``capture_status=deferred`` with a
``defer_until`` (+2h) and schedules a backstop escalation. ``send_capture_prompts``
notifies the thread owner for a meeting that ended ≤N min ago with no capture
(MEETING_CAPTURE), idempotent via ``capture_status``.

The surface is gated by ``_can_access_joseph`` and is CSP-safe (POST forms /
Alpine, no inline onclick/onsubmit; nonce on every <script>).
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.joseph.models import (
    CalendarEvent,
    ExtractedItem,
    ExtractedMeeting,
    VoiceNote,
)
from apps.notifications.models import EventType, Notification


# --------------------------------------------------------------------------
# fixtures (reuse the established joseph/owner pattern)
# --------------------------------------------------------------------------


@pytest.fixture
def joseph(client, org_owner, workspace):
    """Joseph = an owner of the workspace (can access the principal surface)."""
    from apps.members.models import WorkspaceMembership

    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def viewer(client, db, organization, workspace):
    """An ordinary workspace member (viewer) — must not reach the capture surface."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


def _thread(*, owner=None, org_name="Rockefeller Foundation", track="energy"):
    from apps.crm.models import Organization, OutreachThread

    org = Organization.objects.create(name=org_name)
    return OutreachThread.objects.create(org=org, track=track, owner=owner)


def _event(workspace, thread, *, ended_min_ago=None, capture_status="none", gid="cap1"):
    """A linked CalendarEvent that has already ended ``ended_min_ago`` minutes ago."""
    now = timezone.now()
    end = now - timedelta(minutes=ended_min_ago) if ended_min_ago is not None else now + timedelta(hours=1)
    start = end - timedelta(hours=1)
    return CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id=gid,
        title=f"{thread.org.name} sync",
        start=start,
        end=end,
        linked_thread_id=str(thread.id),
        briefing_status="briefed",
        capture_status=capture_status,
    )


def _audio():
    return SimpleUploadedFile("note.m4a", b"FAKE-AUDIO-BYTES", content_type="audio/mp4")


# --------------------------------------------------------------------------
# event type
# --------------------------------------------------------------------------


def test_meeting_capture_event_type_exists():
    assert EventType.MEETING_CAPTURE == "meeting_capture"
    assert "meeting_capture" in EventType.values


# --------------------------------------------------------------------------
# GET /joseph/capture/<thread_id>/ — the three-path surface
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_capture_get_renders_three_paths(client, joseph, workspace):
    thread = _thread(owner=joseph)
    resp = client.get(reverse("joseph:capture", args=[str(thread.id)]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # voice record path
    assert reverse("joseph:capture-voice", args=[str(thread.id)]) in body
    # quick form path with its five fields
    assert reverse("joseph:capture-form", args=[str(thread.id)]) in body
    for field in ("commitments", "next_step", "due_date", "warmth_delta", "share"):
        assert f'name="{field}"' in body
    # defer path
    assert reverse("joseph:capture-defer", args=[str(thread.id)]) in body


@pytest.mark.django_db
def test_capture_get_is_csp_safe(client, joseph, workspace):
    thread = _thread(owner=joseph)
    resp = client.get(reverse("joseph:capture", args=[str(thread.id)]))
    body = resp.content.decode()
    assert "onclick=" not in body
    assert "onsubmit=" not in body
    # every INLINE <script> (no external src) carries a CSP nonce — an external
    # src script is governed by the script-src allowlist, not a nonce.
    import re

    for tag in re.findall(r"<script\b[^>]*>", body):
        if "src=" in tag:
            continue
        assert "nonce=" in tag


@pytest.mark.django_db
def test_capture_get_role_gated(client, viewer, workspace):
    thread = _thread()
    resp = client.get(reverse("joseph:capture", args=[str(thread.id)]))
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# POST .../voice/ — multipart upload → VoiceNote + enqueue extraction
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_voice_upload_creates_voice_note_and_enqueues_extraction(client, joseph, workspace):
    thread = _thread(owner=joseph)
    event = _event(workspace, thread, ended_min_ago=10)
    url = reverse("joseph:capture-voice", args=[str(thread.id)])
    with patch("apps.joseph.views.extract_meeting") as extract_mock:
        resp = client.post(
            url, {"audio": _audio(), "google_event_id": event.google_event_id}
        )
    assert resp.status_code in (200, 302)
    note = VoiceNote.objects.get(thread=thread)
    assert note.status == VoiceNote.Status.UPLOADED
    assert note.created_by_id == joseph.id
    assert note.calendar_event_id == event.id
    # the file is written to the configured storage
    assert note.file.name
    # extraction enqueued with the new note's id
    extract_mock.delay.assert_called_once_with(str(note.id))


@pytest.mark.django_db
def test_voice_upload_marks_event_captured(client, joseph, workspace):
    thread = _thread(owner=joseph)
    event = _event(workspace, thread, ended_min_ago=10)
    url = reverse("joseph:capture-voice", args=[str(thread.id)])
    with patch("apps.joseph.views.extract_meeting"):
        client.post(url, {"audio": _audio(), "google_event_id": event.google_event_id})
    event.refresh_from_db()
    assert event.capture_status == "captured"


@pytest.mark.django_db
def test_voice_upload_role_gated(client, viewer, workspace):
    thread = _thread()
    url = reverse("joseph:capture-voice", args=[str(thread.id)])
    with patch("apps.joseph.views.extract_meeting"):
        resp = client.post(url, {"audio": _audio()})
    assert resp.status_code == 403
    assert not VoiceNote.objects.exists()


# --------------------------------------------------------------------------
# POST .../form/ — quick form → ExtractedMeeting(source=form) + items
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_form_capture_creates_pending_meeting_with_items(client, joseph, workspace):
    thread = _thread(owner=joseph)
    event = _event(workspace, thread, ended_min_ago=10)
    url = reverse("joseph:capture-form", args=[str(thread.id)])
    resp = client.post(
        url,
        {
            "commitments": "They will fund 2M over 3 years",
            "next_step": "Send the concept note by Friday",
            "due_date": "2026-07-01",
            "warmth_delta": "warmer",
            "share": "on",
            "google_event_id": event.google_event_id,
        },
    )
    assert resp.status_code in (200, 302)
    meeting = ExtractedMeeting.objects.get(thread=thread)
    assert meeting.source == ExtractedMeeting.Source.FORM
    assert meeting.status == ExtractedMeeting.Status.PENDING
    assert meeting.warmth_delta == "warmer"
    assert meeting.voice_note_id is None
    kinds = set(meeting.items.values_list("kind", flat=True))
    # a commitment line and a next-step line both became items
    assert ExtractedItem.Kind.NEXT_STEP in kinds
    assert any(k.startswith("commitment_") for k in kinds)
    # the next-step item carries the proposed due date
    nxt = meeting.items.get(kind=ExtractedItem.Kind.NEXT_STEP)
    assert str(nxt.proposed_due) == "2026-07-01"


@pytest.mark.django_db
def test_form_capture_no_transcription(client, joseph, workspace):
    """The form path never touches the transcription/extraction pipeline."""
    thread = _thread(owner=joseph)
    url = reverse("joseph:capture-form", args=[str(thread.id)])
    with patch("apps.joseph.views.extract_meeting") as extract_mock:
        client.post(url, {"next_step": "Follow up", "warmth_delta": "same"})
    extract_mock.delay.assert_not_called()
    assert not VoiceNote.objects.exists()


@pytest.mark.django_db
def test_form_capture_marks_event_captured(client, joseph, workspace):
    thread = _thread(owner=joseph)
    event = _event(workspace, thread, ended_min_ago=10)
    url = reverse("joseph:capture-form", args=[str(thread.id)])
    client.post(
        url,
        {"next_step": "Follow up", "warmth_delta": "same", "google_event_id": event.google_event_id},
    )
    event.refresh_from_db()
    assert event.capture_status == "captured"


@pytest.mark.django_db
def test_form_capture_role_gated(client, viewer, workspace):
    thread = _thread()
    url = reverse("joseph:capture-form", args=[str(thread.id)])
    resp = client.post(url, {"next_step": "x"})
    assert resp.status_code == 403
    assert not ExtractedMeeting.objects.exists()


# --------------------------------------------------------------------------
# POST .../defer/ — defer + escalation
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_defer_sets_capture_status_and_defer_until(client, joseph, workspace):
    thread = _thread(owner=joseph)
    event = _event(workspace, thread, ended_min_ago=10)
    url = reverse("joseph:capture-defer", args=[str(thread.id)])
    before = timezone.now()
    resp = client.post(url, {"google_event_id": event.google_event_id})
    assert resp.status_code in (200, 302)
    event.refresh_from_db()
    assert event.capture_status == "deferred"
    assert event.defer_until is not None
    # deferred ~2h out
    delta = event.defer_until - before
    assert timedelta(hours=1, minutes=50) <= delta <= timedelta(hours=2, minutes=10)


@pytest.mark.django_db
def test_defer_role_gated(client, viewer, workspace):
    thread = _thread()
    event = _event(workspace, _thread(org_name="Other"), gid="cap-other")
    url = reverse("joseph:capture-defer", args=[str(thread.id)])
    resp = client.post(url, {"google_event_id": event.google_event_id})
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# send_capture_prompts — beat-driven prompt for ended-but-uncaptured meetings
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_send_capture_prompts_notifies_owner(joseph, workspace):
    from apps.joseph.capture import send_capture_prompts

    thread = _thread(owner=joseph)
    event = _event(workspace, thread, ended_min_ago=10)
    send_capture_prompts()
    event.refresh_from_db()
    assert event.capture_status == "prompted"
    assert Notification.objects.filter(
        user=joseph, event_type=EventType.MEETING_CAPTURE
    ).exists()


@pytest.mark.django_db
def test_send_capture_prompts_is_idempotent(joseph, workspace):
    from apps.joseph.capture import send_capture_prompts

    thread = _thread(owner=joseph)
    _event(workspace, thread, ended_min_ago=10)
    send_capture_prompts()
    send_capture_prompts()
    assert (
        Notification.objects.filter(
            user=joseph, event_type=EventType.MEETING_CAPTURE
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_send_capture_prompts_skips_captured_and_future(joseph, workspace):
    from apps.joseph.capture import send_capture_prompts

    thread = _thread(owner=joseph)
    # already captured → no prompt
    _event(workspace, thread, ended_min_ago=10, capture_status="captured", gid="done")
    # still in the future → no prompt
    _event(workspace, _thread(owner=joseph, org_name="Future"), gid="future")
    send_capture_prompts()
    assert not Notification.objects.filter(event_type=EventType.MEETING_CAPTURE).exists()


@pytest.mark.django_db
def test_capture_prompt_task_invokes_sweep(joseph, workspace):
    thread = _thread(owner=joseph)
    _event(workspace, thread, ended_min_ago=10)
    from apps.joseph.tasks import run_capture_prompts

    run_capture_prompts()
    assert Notification.objects.filter(event_type=EventType.MEETING_CAPTURE).exists()


# --------------------------------------------------------------------------
# defer escalation — backstop notify after 24h if still uncaptured
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_defer_escalation_notifies_backstop_after_24h(joseph, workspace):
    from apps.joseph.capture import escalate_deferred_captures

    backstop = _make_backstop(workspace)
    thread = _thread(owner=joseph)
    thread.backstop = backstop
    thread.save(update_fields=["backstop"])
    event = _event(workspace, thread, ended_min_ago=10, capture_status="deferred", gid="defer1")
    # deferred 25h ago, still uncaptured → escalate to the backstop
    event.defer_until = timezone.now() - timedelta(hours=25)
    event.save(update_fields=["defer_until"])
    escalate_deferred_captures()
    assert Notification.objects.filter(
        user=backstop, event_type=EventType.MEETING_CAPTURE
    ).exists()


def _make_backstop(workspace):
    from apps.accounts.models import User
    from apps.members.models import WorkspaceMembership

    u = User.objects.create_user(
        email="nduta@example.com", password="x", name="Nduta", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="admin")
    return u


# --------------------------------------------------------------------------
# beat wiring
# --------------------------------------------------------------------------


def test_beat_schedule_has_capture_prompts_entry():
    from jobs.schedules import BEAT_SCHEDULE

    entry = BEAT_SCHEDULE["joseph-capture-prompts"]
    assert entry["task"] == "apps.joseph.tasks.run_capture_prompts"
