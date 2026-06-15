"""Task 9 — ownership bookkeeping for the outreach engine.

``docs/TABLE_OWNERSHIP.md`` is the source-of-truth for the strangler split. The
outreach tables (mailbox, sends, sequences, suppression) are Django-owned, and
the agent-service ``daily_sequences_and_noreply`` beat is retired (it operated
on agent-service threads that no longer exist).
"""
from pathlib import Path

from django.conf import settings


def _ownership_text() -> str:
    doc = Path(settings.BASE_DIR) / "docs" / "TABLE_OWNERSHIP.md"
    assert doc.exists(), "docs/TABLE_OWNERSHIP.md must exist"
    return doc.read_text().lower()


def test_outreach_tables_are_django_owned():
    text = _ownership_text()
    for table in ("mailbox", "mailboxsend", "sequence", "suppression"):
        assert table in text, f"{table} must be listed in TABLE_OWNERSHIP.md"
    # outreach lives in apps/outreach, owned by Django
    assert "apps/outreach" in text
    assert "django" in text


def test_agent_service_sequences_beat_is_retired():
    text = _ownership_text()
    # The doc must record that the agent-service sequences beat no longer runs.
    assert "daily_sequences_and_noreply" in text
    assert "retired" in text
