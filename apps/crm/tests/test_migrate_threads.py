"""Tests for the one-time migration command pulling threads from agent-service.

The command ``import_threads_from_agent_service`` calls
``apps.common.agent_client.agent_get("/threads")`` and creates / updates the
canonical Django CRM rows (Organization, Contact, OutreachThread). It is
idempotent (matched on ``agent_thread_id`` + org-name/contact-email) and
supports ``--dry-run`` (no writes).
"""
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.crm.models import Contact, Organization, OutreachThread

ONE_THREAD = {
    "items": [
        {
            "id": "t1",
            "org": "Rockefeller",
            "contact_name": "Dr. Okonkwo",
            "contact_email": "a@b.org",
            "stage": "engaged",
            "track": "ai10bn",
            "quintile": 4,
            "traffic_light": "amber",
            "score": 0.7,
            "dossier_id": "d1",
        }
    ]
}

CMD = "import_threads_from_agent_service"
GET_PATH = "apps.crm.management.commands.import_threads_from_agent_service.agent_get"


def _run(**kwargs):
    out = StringIO()
    call_command(CMD, stdout=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db
def test_import_creates_org_contact_thread():
    with patch(GET_PATH, return_value=ONE_THREAD):
        _run()

    org = Organization.objects.get(name="Rockefeller")
    contact = Contact.objects.get(email="a@b.org")
    assert contact.org_id == org.id
    assert contact.full_name == "Dr. Okonkwo"

    thread = OutreachThread.objects.get(agent_thread_id="t1")
    assert thread.org_id == org.id
    assert thread.primary_contact_id == contact.id
    assert thread.stage == "engaged"
    assert thread.track == "ai10bn"
    assert thread.quintile == 4
    assert thread.traffic_light == "amber"
    assert thread.score == 0.7
    assert thread.dossier_id == "d1"


@pytest.mark.django_db
def test_import_is_idempotent():
    with patch(GET_PATH, return_value=ONE_THREAD):
        _run()
        _run()

    assert Organization.objects.filter(name="Rockefeller").count() == 1
    assert Contact.objects.filter(email="a@b.org").count() == 1
    assert OutreachThread.objects.filter(agent_thread_id="t1").count() == 1


@pytest.mark.django_db
def test_import_reuses_existing_org_and_contact():
    """A pre-existing org/contact (e.g. from a spreadsheet import) is reused,
    not duplicated."""
    org = Organization.objects.create(name="Rockefeller", type="funder")
    Contact.objects.create(org=org, full_name="Dr. Okonkwo", email="a@b.org")

    with patch(GET_PATH, return_value=ONE_THREAD):
        _run()

    assert Organization.objects.filter(name="Rockefeller").count() == 1
    assert Contact.objects.filter(email="a@b.org").count() == 1
    thread = OutreachThread.objects.get(agent_thread_id="t1")
    assert thread.org_id == org.id
    assert thread.primary_contact.email == "a@b.org"


@pytest.mark.django_db
def test_import_updates_existing_thread_fields():
    with patch(GET_PATH, return_value=ONE_THREAD):
        _run()

    advanced = {
        "items": [dict(ONE_THREAD["items"][0], stage="proposal_sent", quintile=5)]
    }
    with patch(GET_PATH, return_value=advanced):
        _run()

    thread = OutreachThread.objects.get(agent_thread_id="t1")
    assert thread.stage == "proposal_sent"
    assert thread.quintile == 5
    assert OutreachThread.objects.filter(agent_thread_id="t1").count() == 1


@pytest.mark.django_db
def test_dry_run_creates_nothing():
    with patch(GET_PATH, return_value=ONE_THREAD):
        _run(dry_run=True)

    assert Organization.objects.count() == 0
    assert Contact.objects.count() == 0
    assert OutreachThread.objects.count() == 0


@pytest.mark.django_db
def test_import_prints_counts():
    with patch(GET_PATH, return_value=ONE_THREAD):
        out = _run()

    assert "created" in out.lower()
