"""Tests for apps.joseph.models — GoogleIntegration + CalendarEvent.

GoogleIntegration stores a per-user OAuth refresh token (encrypted at rest)
plus the granted scopes; CalendarEvent is the Django-side mirror of a Google
Calendar event, optionally fuzzy-linked to an agent-service thread. Both back
the calendar feed (Task 10) and the Today strip on Joseph's home (Task 3).
"""
from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.joseph.models import CalendarEvent, GoogleIntegration


@pytest.mark.django_db
def test_google_integration_round_trip_and_encrypts_refresh_token(user):
    gi = GoogleIntegration.objects.create(
        user=user,
        refresh_token="1//super-secret-refresh-token",
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    fetched = GoogleIntegration.objects.get(pk=gi.pk)
    # refresh_token round-trips through the EncryptedTextField
    assert fetched.refresh_token == "1//super-secret-refresh-token"
    assert fetched.scopes == ["https://www.googleapis.com/auth/calendar.readonly"]
    # last_synced_at is nullable and unset on creation
    assert fetched.last_synced_at is None
    # ciphertext at rest is not the plaintext
    raw = GoogleIntegration.objects.filter(pk=gi.pk).values_list("refresh_token", flat=True).first()
    # (values_list runs from_db_value → decrypts; re-read the column directly)
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            f"SELECT refresh_token FROM {GoogleIntegration._meta.db_table} WHERE id = %s",
            [str(gi.pk)],
        )
        stored = cur.fetchone()[0]
    assert stored != "1//super-secret-refresh-token"


@pytest.mark.django_db
def test_calendar_event_round_trip_and_defaults(workspace):
    start = timezone.now() + timedelta(hours=2)
    end = start + timedelta(hours=1)
    ev = CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id="g1",
        title="Rockefeller sync",
        start=start,
        end=end,
        attendees=[{"email": "officer@rockfound.org"}],
    )
    fetched = CalendarEvent.objects.get(pk=ev.pk)
    assert fetched.title == "Rockefeller sync"
    assert fetched.attendees == [{"email": "officer@rockfound.org"}]
    # linked_thread_id defaults to "" (unlinked); briefing_status defaults "none"
    assert fetched.linked_thread_id == ""
    assert fetched.briefing_status == "none"
    assert fetched.raw == {}


@pytest.mark.django_db
def test_calendar_event_google_event_id_unique(workspace):
    start = timezone.now()
    CalendarEvent.objects.create(
        workspace=workspace, google_event_id="dup", title="A", start=start
    )
    with pytest.raises(IntegrityError):
        CalendarEvent.objects.create(
            workspace=workspace, google_event_id="dup", title="B", start=start
        )


@pytest.mark.django_db
def test_calendar_event_linked_thread_id_settable(workspace):
    ev = CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id="g2",
        title="Linked",
        start=timezone.now(),
        linked_thread_id="t-123",
        briefing_status="ready",
    )
    fetched = CalendarEvent.objects.get(pk=ev.pk)
    assert fetched.linked_thread_id == "t-123"
    assert fetched.briefing_status == "ready"
