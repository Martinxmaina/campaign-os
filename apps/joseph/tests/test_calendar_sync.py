"""Tests for the Google Calendar feed (Task 10).

The sync task builds a Calendar client from a stored ``GoogleIntegration``,
pulls upcoming events, fuzzy-matches each event's title/attendees against the
org names of agent-service threads, and upserts a ``CalendarEvent`` row —
auto-linking on a confident (>0.9) match, leaving ambiguous ones unlinked so
they surface as linkage suggestions in the action queue.

Everything is exercised with the Google client and the agent-service reader
patched out, so no network is touched. With no ``GoogleIntegration`` present
the task must no-op (``{"skipped": "no-credentials"}``) so the feature is safe
to deploy before Joseph's OAuth re-consent.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.joseph.models import CalendarEvent, GoogleIntegration


def _event(eid, summary, start, end=None, attendees=None):
    """Build a Google Calendar API v3 event resource dict."""
    return {
        "id": eid,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (end or start + timedelta(hours=1)).isoformat()},
        "attendees": attendees or [],
    }


@pytest.fixture
def integration(db, user, workspace):
    from apps.members.models import WorkspaceMembership

    WorkspaceMembership.objects.create(
        user=user,
        workspace=workspace,
        workspace_role=WorkspaceMembership.WorkspaceRole.PRINCIPAL,
    )
    return GoogleIntegration.objects.create(
        user=user,
        refresh_token="1//refresh",
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )


# ---------------------------------------------------------------------------
# task registration
# ---------------------------------------------------------------------------


def test_sync_google_calendar_is_a_shared_task():
    from apps.joseph import tasks

    assert hasattr(tasks.sync_google_calendar, "delay")


@pytest.mark.django_db
def test_calendar_sync_registered_in_beat():
    from django.conf import settings

    tasks_registered = [e["task"] for e in settings.CELERY_BEAT_SCHEDULE.values()]
    assert "apps.joseph.tasks.sync_google_calendar" in tasks_registered


# ---------------------------------------------------------------------------
# no-credentials no-op
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_integration_returns_skipped_no_credentials():
    from apps.joseph import tasks

    result = tasks.sync_google_calendar()
    assert result == {"skipped": "no-credentials"}


# ---------------------------------------------------------------------------
# upsert + fuzzy auto-link
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_confident_match_auto_links_event_to_thread(integration, workspace):
    from apps.joseph import tasks

    start = timezone.now() + timedelta(days=1)
    events = [_event("g-rock", "Rockefeller Foundation strategy", start)]
    threads = [{"id": "t-rock", "org": "Rockefeller Foundation"}]

    with patch.object(tasks, "upcoming_events", return_value=events), patch.object(
        tasks, "build_calendar_service", return_value=object()
    ), patch("apps.joseph.readers.list_threads", return_value=threads):
        result = tasks.sync_google_calendar()

    ev = CalendarEvent.objects.get(google_event_id="g-rock")
    assert ev.workspace_id == workspace.id
    assert ev.title == "Rockefeller Foundation strategy"
    assert ev.linked_thread_id == "t-rock"
    assert result["linked"] == 1


@pytest.mark.django_db
def test_ambiguous_title_stays_unlinked(integration):
    from apps.joseph import tasks

    start = timezone.now() + timedelta(days=1)
    events = [_event("g-misc", "Weekly team standup", start)]
    threads = [{"id": "t-rock", "org": "Rockefeller Foundation"}]

    with patch.object(tasks, "upcoming_events", return_value=events), patch.object(
        tasks, "build_calendar_service", return_value=object()
    ), patch("apps.joseph.readers.list_threads", return_value=threads):
        tasks.sync_google_calendar()

    ev = CalendarEvent.objects.get(google_event_id="g-misc")
    assert ev.linked_thread_id == ""


@pytest.mark.django_db
def test_upsert_is_idempotent(integration):
    from apps.joseph import tasks

    start = timezone.now() + timedelta(days=1)
    events = [_event("g-rock", "Rockefeller Foundation strategy", start)]
    threads = [{"id": "t-rock", "org": "Rockefeller Foundation"}]

    with patch.object(tasks, "upcoming_events", return_value=events), patch.object(
        tasks, "build_calendar_service", return_value=object()
    ), patch("apps.joseph.readers.list_threads", return_value=threads):
        tasks.sync_google_calendar()
        tasks.sync_google_calendar()

    assert CalendarEvent.objects.filter(google_event_id="g-rock").count() == 1


@pytest.mark.django_db
def test_confident_auto_link_creates_notification(integration):
    from apps.joseph import tasks

    start = timezone.now() + timedelta(days=1)
    events = [_event("g-rock", "Rockefeller Foundation strategy", start)]
    threads = [{"id": "t-rock", "org": "Rockefeller Foundation"}]

    with patch.object(tasks, "upcoming_events", return_value=events), patch.object(
        tasks, "build_calendar_service", return_value=object()
    ), patch("apps.joseph.readers.list_threads", return_value=threads), patch(
        "apps.joseph.readers.create_notification", return_value={}
    ) as notify:
        tasks.sync_google_calendar()

    assert notify.called


# ---------------------------------------------------------------------------
# fuzzy matcher unit
# ---------------------------------------------------------------------------


def test_best_thread_match_returns_high_confidence_for_exact_org():
    from apps.joseph.tasks import best_thread_match

    threads = [{"id": "t-rock", "org": "Rockefeller Foundation"}]
    thread_id, score = best_thread_match("Rockefeller Foundation strategy", [], threads)
    assert thread_id == "t-rock"
    assert score > 0.9


def test_best_thread_match_low_for_unrelated_title():
    from apps.joseph.tasks import best_thread_match

    threads = [{"id": "t-rock", "org": "Rockefeller Foundation"}]
    thread_id, score = best_thread_match("Weekly team standup", [], threads)
    assert score < 0.9


def test_best_thread_match_matches_on_attendee_domain():
    from apps.joseph.tasks import best_thread_match

    threads = [{"id": "t-rock", "org": "Rockefeller Foundation"}]
    attendees = [{"email": "officer@rockefellerfoundation.org"}]
    # title gives no signal; the attendee org token carries the match
    thread_id, score = best_thread_match("Catch-up call", attendees, threads)
    assert thread_id == "t-rock"
    assert score > 0.6


# ---------------------------------------------------------------------------
# client builder
# ---------------------------------------------------------------------------


def test_build_calendar_service_uses_refresh_token():
    from integrations import google_calendar

    captured = {}

    class _Creds:
        def __init__(self, **kw):
            captured.update(kw)

    with patch.object(google_calendar, "Credentials", _Creds), patch.object(
        google_calendar, "build", return_value="svc"
    ) as build:
        svc = google_calendar.build_calendar_service(
            type("GI", (), {"refresh_token": "1//rt", "scopes": ["s"]})()
        )

    assert svc == "svc"
    assert captured["refresh_token"] == "1//rt"
    build.assert_called_once()
