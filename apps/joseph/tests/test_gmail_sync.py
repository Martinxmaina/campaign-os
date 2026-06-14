"""Tests for the Gmail inbound feed (Task 11).

The sync task builds a Gmail client from a stored ``GoogleIntegration``, pulls
the messages that have arrived since the last sync, and POSTs each one to the
agent-service ``/ingest`` endpoint with ``source_type="email_inbound"`` and the
per-feed ``X-Ingest-Key`` header (Phase 0 contract) — so the intelligence plane
can fold Joseph's inbound mail into its thread/dossier graph.

Everything is exercised with the Gmail client and the ingest POST patched out,
so no network is touched. With no ``GoogleIntegration`` present the task must
no-op (``{"skipped": "no-credentials"}``) so the feature is safe to deploy
before Joseph's OAuth re-consent.
"""
from unittest.mock import patch

import pytest

from apps.joseph.models import GoogleIntegration

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def _message(mid, subject, sender, snippet="hi"):
    """Build a minimal Gmail API v1 message resource dict (as recent_messages
    would normalize it for the task)."""
    return {
        "id": mid,
        "thread_id": f"thr-{mid}",
        "subject": subject,
        "from": sender,
        "snippet": snippet,
        "internal_date": "1700000000000",
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
        scopes=[GMAIL_SCOPE],
    )


# ---------------------------------------------------------------------------
# task registration
# ---------------------------------------------------------------------------


def test_sync_google_gmail_is_a_shared_task():
    from apps.joseph import tasks

    assert hasattr(tasks.sync_google_gmail, "delay")


@pytest.mark.django_db
def test_gmail_sync_registered_in_beat():
    from django.conf import settings

    tasks_registered = [e["task"] for e in settings.CELERY_BEAT_SCHEDULE.values()]
    assert "apps.joseph.tasks.sync_google_gmail" in tasks_registered


# ---------------------------------------------------------------------------
# no-credentials no-op
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_integration_returns_skipped_no_credentials():
    from apps.joseph import tasks

    result = tasks.sync_google_gmail()
    assert result == {"skipped": "no-credentials"}


# ---------------------------------------------------------------------------
# fetch → POST to /ingest (source_type=email_inbound)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_messages_posted_to_ingest_as_email_inbound(integration):
    from apps.joseph import tasks

    messages = [
        _message("m1", "Partnership proposal", "officer@rockefellerfoundation.org"),
        _message("m2", "Re: site visit", "dennis@africacen.org"),
    ]

    with patch.object(tasks, "recent_messages", return_value=messages), patch.object(
        tasks, "build_gmail_service", return_value=object()
    ), patch.object(tasks, "post_to_ingest", return_value={"ok": True}) as ingest:
        result = tasks.sync_google_gmail()

    assert ingest.call_count == 2
    # every call uses the email_inbound source type
    for call in ingest.call_args_list:
        assert call.kwargs["source_type"] == "email_inbound"
    # the message identity flows through source_id / payload
    posted_ids = {c.kwargs["source_id"] for c in ingest.call_args_list}
    assert posted_ids == {"m1", "m2"}
    assert result["ingested"] == 2


@pytest.mark.django_db
def test_ingest_payload_carries_message_fields(integration):
    from apps.joseph import tasks

    messages = [_message("m1", "Partnership proposal", "officer@example.org", "hello")]

    with patch.object(tasks, "recent_messages", return_value=messages), patch.object(
        tasks, "build_gmail_service", return_value=object()
    ), patch.object(tasks, "post_to_ingest", return_value={"ok": True}) as ingest:
        tasks.sync_google_gmail()

    payload = ingest.call_args.kwargs["payload"]
    assert payload["subject"] == "Partnership proposal"
    assert payload["from"] == "officer@example.org"
    assert payload["snippet"] == "hello"
    assert ingest.call_args.kwargs["dedupe_key"] == "email_inbound:m1"


@pytest.mark.django_db
def test_empty_inbox_ingests_nothing(integration):
    from apps.joseph import tasks

    with patch.object(tasks, "recent_messages", return_value=[]), patch.object(
        tasks, "build_gmail_service", return_value=object()
    ), patch.object(tasks, "post_to_ingest") as ingest:
        result = tasks.sync_google_gmail()

    assert not ingest.called
    assert result["ingested"] == 0


@pytest.mark.django_db
def test_ingest_failure_for_one_message_does_not_abort_the_rest(integration):
    from apps.joseph import tasks

    messages = [_message("m1", "a", "x@y.org"), _message("m2", "b", "z@y.org")]

    def _ingest(**kw):
        if kw["source_id"] == "m1":
            raise RuntimeError("boom")
        return {"ok": True}

    with patch.object(tasks, "recent_messages", return_value=messages), patch.object(
        tasks, "build_gmail_service", return_value=object()
    ), patch.object(tasks, "post_to_ingest", side_effect=_ingest):
        result = tasks.sync_google_gmail()

    # m2 still ingested even though m1 failed
    assert result["ingested"] == 1


@pytest.mark.django_db
def test_last_synced_at_is_updated(integration):
    from apps.joseph import tasks

    messages = [_message("m1", "a", "x@y.org")]
    assert integration.last_synced_at is None

    with patch.object(tasks, "recent_messages", return_value=messages), patch.object(
        tasks, "build_gmail_service", return_value=object()
    ), patch.object(tasks, "post_to_ingest", return_value={"ok": True}):
        tasks.sync_google_gmail()

    integration.refresh_from_db()
    assert integration.last_synced_at is not None


@pytest.mark.django_db
def test_fetch_failure_keeps_other_integrations_going(db, django_user_model):
    from apps.joseph import tasks

    u1 = django_user_model.objects.create_user(
        email="a@example.org", password="x"
    )
    u2 = django_user_model.objects.create_user(
        email="b@example.org", password="x"
    )
    GoogleIntegration.objects.create(user=u1, refresh_token="rt1", scopes=[GMAIL_SCOPE])
    GoogleIntegration.objects.create(user=u2, refresh_token="rt2", scopes=[GMAIL_SCOPE])

    def _recent(service, since=None):
        # First integration raises, second returns one message.
        if getattr(service, "_fail", False):
            raise RuntimeError("auth")
        return [_message("m1", "a", "x@y.org")]

    def _build(integration):
        svc = type("S", (), {})()
        svc._fail = integration.user_id == u1.id
        return svc

    with patch.object(tasks, "recent_messages", side_effect=_recent), patch.object(
        tasks, "build_gmail_service", side_effect=_build
    ), patch.object(tasks, "post_to_ingest", return_value={"ok": True}) as ingest:
        result = tasks.sync_google_gmail()

    assert ingest.call_count == 1
    assert result["ingested"] == 1


# ---------------------------------------------------------------------------
# client builder + fetch (integrations/gmail.py)
# ---------------------------------------------------------------------------


def test_build_gmail_service_uses_refresh_token():
    from integrations import gmail

    captured = {}

    class _Creds:
        def __init__(self, **kw):
            captured.update(kw)

    # google libs are imported lazily inside build_gmail_service (so the Celery
    # worker can autodiscover the task without google installed), so patch the
    # real import sources, not module-level names.
    with patch("google.oauth2.credentials.Credentials", _Creds), patch(
        "googleapiclient.discovery.build", return_value="svc"
    ) as build:
        svc = gmail.build_gmail_service(
            type("GI", (), {"refresh_token": "1//rt", "scopes": ["s"]})()
        )

    assert svc == "svc"
    assert captured["refresh_token"] == "1//rt"
    build.assert_called_once()


def test_recent_messages_lists_and_fetches_each_message():
    """recent_messages: list inbox message ids, then fetch+normalize each."""
    from integrations import gmail

    list_resp = {"messages": [{"id": "m1"}, {"id": "m2"}]}
    raw = {
        "m1": {
            "id": "m1",
            "threadId": "thr-1",
            "snippet": "hello there",
            "internalDate": "1700000000000",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Partnership proposal"},
                    {"name": "From", "value": "officer@example.org"},
                ]
            },
        },
        "m2": {
            "id": "m2",
            "threadId": "thr-2",
            "snippet": "second",
            "internalDate": "1700000001000",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Re: site visit"},
                    {"name": "From", "value": "dennis@example.org"},
                ]
            },
        },
    }

    class _Get:
        def __init__(self, mid):
            self._mid = mid

        def execute(self):
            return raw[self._mid]

    class _Messages:
        def list(self, **kw):
            return type("L", (), {"execute": staticmethod(lambda: list_resp)})()

        def get(self, *, userId, id, format=None):  # noqa: N803
            return _Get(id)

    class _Users:
        def messages(self):
            return _Messages()

    service = type("Svc", (), {"users": lambda self: _Users()})()

    msgs = gmail.recent_messages(service)
    assert {m["id"] for m in msgs} == {"m1", "m2"}
    m1 = next(m for m in msgs if m["id"] == "m1")
    assert m1["subject"] == "Partnership proposal"
    assert m1["from"] == "officer@example.org"
    assert m1["thread_id"] == "thr-1"
    assert m1["snippet"] == "hello there"


def test_recent_messages_empty_when_no_messages():
    from integrations import gmail

    class _Messages:
        def list(self, **kw):
            return type("L", (), {"execute": staticmethod(lambda: {})})()

    class _Users:
        def messages(self):
            return _Messages()

    service = type("Svc", (), {"users": lambda self: _Users()})()
    assert gmail.recent_messages(service) == []
