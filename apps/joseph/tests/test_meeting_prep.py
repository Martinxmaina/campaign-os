"""Tests for the pre-meeting cascade T-5 / T-2 / T-0 (TB.3).

``meeting_prep.check_meeting_prep`` walks every linked, future CalendarEvent and
fires the right cascade stage for the days-to-start window, idempotently (a stage
already in ``prep_stages`` never re-fires). The T-2 stage drafts talking points
(3 bullets per track) via ``talking_points.draft`` and runs them through the same
status-language Pass-1 gate the publish path uses (``gate_talking_points``) so a
premature "commitment confirmed" can never land on the brief.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.joseph import meeting_prep, talking_points
from apps.joseph.models import CalendarEvent
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
    return org_owner


def _thread(*, org_name="Rockefeller Foundation", track="energy"):
    from apps.crm.models import Organization, OutreachThread

    org = Organization.objects.create(name=org_name)
    return OutreachThread.objects.create(org=org, track=track, owner=None)


def _linked_event(workspace, thread, *, days_out, gid="g1", briefing_status="linked"):
    return CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id=gid,
        title=f"{thread.org.name} sync",
        start=timezone.now() + timedelta(days=days_out),
        linked_thread_id=str(thread.id),
        briefing_status=briefing_status,
    )


# --------------------------------------------------------------------------
# event type
# --------------------------------------------------------------------------


def test_meeting_prep_event_type_exists():
    assert EventType.MEETING_PREP == "meeting_prep"
    assert "meeting_prep" in EventType.values


# --------------------------------------------------------------------------
# talking_points.draft — 3 bullets per track from the L0/dossier
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_draft_returns_three_bullets():
    thread = _thread()
    points = talking_points.draft(thread)
    assert isinstance(points, list)
    assert len(points) == 3
    assert all(isinstance(p, str) and p for p in points)


@pytest.mark.django_db
def test_draft_uses_brief_hook_and_why_now():
    """draft pulls the L0 hook + why-now into the bullets."""
    thread = _thread()
    brief = {
        "who": "Rockefeller Foundation",
        "why_now": "New $2bn climate window just opened",
        "hook": "WAIIS de-risks first-loss capital for African grids",
    }
    with patch("apps.joseph.talking_points.JosephIntelligence") as MockIntel:
        MockIntel.return_value.brief.return_value = brief
        points = talking_points.draft(thread)
    joined = " ".join(points).lower()
    assert "climate window" in joined
    assert "de-risks first-loss" in joined


# --------------------------------------------------------------------------
# gate_talking_points — status-language Pass-1 (no "confirmed" before it is)
# --------------------------------------------------------------------------


def test_gate_passes_clean_points():
    clean = ["We are exploring a partnership", "Discuss the grid pipeline"]
    gated = talking_points.gate_talking_points(clean)
    assert gated == clean


def test_gate_flags_status_language():
    """A banned status-language term ('confirmed'/'committed'/'funded') is
    flagged/rewritten — the raw premature claim never survives verbatim."""
    dirty = ["Their board confirmed the $2bn and committed to fund WAIIS"]
    gated = talking_points.gate_talking_points(dirty)
    joined = " ".join(gated).lower()
    assert "confirmed" not in joined
    assert "committed" not in joined
    # the underlying intent is preserved, just neutralised
    assert "waiis" in joined or "board" in joined


# --------------------------------------------------------------------------
# check_meeting_prep — T-5 / T-2 / T-0 cascade (idempotent)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_t5_fires_dossier_refresh_and_notifies(joseph, workspace):
    thread = _thread()
    ev = _linked_event(workspace, thread, days_out=5)
    with patch("apps.joseph.meeting_prep.readers.compile_dossier") as compile_mock:
        meeting_prep.check_meeting_prep()
    compile_mock.assert_called_once()
    ev.refresh_from_db()
    assert "t5" in ev.prep_stages
    assert Notification.objects.filter(event_type=EventType.MEETING_PREP).exists()


@pytest.mark.django_db
def test_t5_is_idempotent(joseph, workspace):
    thread = _thread()
    ev = _linked_event(workspace, thread, days_out=5)
    with patch("apps.joseph.meeting_prep.readers.compile_dossier") as compile_mock:
        meeting_prep.check_meeting_prep()
        meeting_prep.check_meeting_prep()
    # second run must NOT re-fire the dossier refresh for an already-fired stage
    assert compile_mock.call_count == 1
    ev.refresh_from_db()
    assert ev.prep_stages.count("t5") == 1


@pytest.mark.django_db
def test_t2_drafts_gate_checked_talking_points(joseph, workspace):
    thread = _thread()
    ev = _linked_event(workspace, thread, days_out=2)
    with patch(
        "apps.joseph.meeting_prep.gate_talking_points",
        wraps=talking_points.gate_talking_points,
    ) as gate_mock:
        meeting_prep.check_meeting_prep()
    # the gate ran on the drafted points
    gate_mock.assert_called_once()
    ev.refresh_from_db()
    assert "t2" in ev.prep_stages
    assert len(ev.talking_points) == 3
    assert Notification.objects.filter(event_type=EventType.MEETING_PREP).exists()


@pytest.mark.django_db
def test_t2_talking_points_are_gate_scrubbed(joseph, workspace):
    """Talking points containing a banned status-language phrase are rewritten
    /flagged by the gate before they land on the event."""
    thread = _thread()
    ev = _linked_event(workspace, thread, days_out=2)
    with patch(
        "apps.joseph.meeting_prep.talking_points.draft",
        return_value=["Their board confirmed and committed the funding"],
    ):
        meeting_prep.check_meeting_prep()
    ev.refresh_from_db()
    joined = " ".join(ev.talking_points).lower()
    assert "confirmed" not in joined
    assert "committed" not in joined


@pytest.mark.django_db
def test_t0_marks_brief_ready(joseph, workspace):
    thread = _thread()
    ev = _linked_event(workspace, thread, days_out=0)
    meeting_prep.check_meeting_prep()
    ev.refresh_from_db()
    assert "t0" in ev.prep_stages
    assert ev.briefing_status == "briefed"


@pytest.mark.django_db
def test_unlinked_events_are_skipped(joseph, workspace):
    """An unlinked (no thread) event never fires a cascade stage."""
    CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id="solo",
        title="Dentist",
        start=timezone.now() + timedelta(days=2),
        linked_thread_id="",
    )
    with patch("apps.joseph.meeting_prep.readers.compile_dossier") as compile_mock:
        meeting_prep.check_meeting_prep()
    compile_mock.assert_not_called()
    ev = CalendarEvent.objects.get(google_event_id="solo")
    assert ev.prep_stages == []


@pytest.mark.django_db
def test_past_events_are_skipped(joseph, workspace):
    thread = _thread()
    CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id="past",
        title="Old sync",
        start=timezone.now() - timedelta(days=1),
        linked_thread_id=str(thread.id),
        briefing_status="linked",
    )
    with patch("apps.joseph.meeting_prep.readers.compile_dossier") as compile_mock:
        meeting_prep.check_meeting_prep()
    compile_mock.assert_not_called()


# --------------------------------------------------------------------------
# celery task + beat wiring
# --------------------------------------------------------------------------


def test_beat_schedule_has_meeting_prep_entry():
    from jobs.schedules import BEAT_SCHEDULE

    entry = BEAT_SCHEDULE["joseph-meeting-prep"]
    assert entry["task"] == "apps.joseph.tasks.run_meeting_prep"


@pytest.mark.django_db
def test_run_meeting_prep_task_invokes_cascade(joseph, workspace):
    thread = _thread()
    _linked_event(workspace, thread, days_out=0)
    from apps.joseph.tasks import run_meeting_prep

    run_meeting_prep()
    ev = CalendarEvent.objects.get(google_event_id="g1")
    assert "t0" in ev.prep_stages
