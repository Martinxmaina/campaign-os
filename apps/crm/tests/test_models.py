"""Tests for apps.crm models — the canonical CRM (first strangler step).

Five models: Organization (funder), Contact, OutreachThread, Activity, Task.
These assert round-trip persistence, FK resolution, choice defaults, the
append-only Activity newest-first ordering, and admin registration.
"""
from datetime import timedelta

import pytest
from django.contrib import admin
from django.utils import timezone

from apps.crm.models import Activity, Contact, Organization, OutreachThread, Task


@pytest.mark.django_db
def test_organization_round_trip_and_defaults():
    org = Organization.objects.create(
        name="Rockefeller",
        type="funder",
        tier="tier1_anchor",
        track_tags=["ai10bn"],
    )
    fetched = Organization.objects.get(pk=org.pk)
    assert fetched.name == "Rockefeller"
    assert fetched.type == "funder"
    assert fetched.tier == "tier1_anchor"
    assert fetched.track_tags == ["ai10bn"]
    # blank text/url fields default to "" not None
    assert fetched.website == ""
    assert fetched.linkedin_url == ""
    assert fetched.wiki_slug == ""
    assert fetched.notes == ""
    assert str(fetched) == "Rockefeller"
    # uuid pk + timestamps
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


@pytest.mark.django_db
def test_contact_round_trip_and_fk():
    org = Organization.objects.create(name="Rockefeller")
    contact = Contact.objects.create(
        org=org,
        full_name="Dr. Okonkwo",
        seniority="vp",
        email="x@y.org",
    )
    fetched = Contact.objects.get(pk=contact.pk)
    assert fetched.full_name == "Dr. Okonkwo"
    assert fetched.seniority == "vp"
    assert fetched.email == "x@y.org"
    assert fetched.org_id == org.id
    # reverse accessor
    assert list(org.contacts.all()) == [fetched]
    # json/blank defaults
    assert fetched.consent_flags == {}
    assert fetched.last_verified is None
    assert str(fetched) == "Dr. Okonkwo"


@pytest.mark.django_db
def test_outreach_thread_round_trip_and_fks(user):
    org = Organization.objects.create(name="Rockefeller")
    contact = Contact.objects.create(org=org, full_name="Dr. Okonkwo", email="x@y.org")
    thread = OutreachThread.objects.create(
        org=org,
        primary_contact=contact,
        owner=user,
        stage="engaged",
        track="ai10bn",
    )
    fetched = OutreachThread.objects.get(pk=thread.pk)
    # FKs resolve
    assert fetched.org == org
    assert fetched.primary_contact == contact
    assert fetched.owner == user
    assert fetched.stage == "engaged"
    assert fetched.track == "ai10bn"
    # numeric + string defaults
    assert fetched.score == 0.0
    assert fetched.quintile == 0
    assert fetched.traffic_light == "green"
    assert fetched.restricted is False
    assert fetched.dossier_id == ""
    assert fetched.agent_thread_id == ""
    # reverse accessors
    assert list(org.threads.all()) == [fetched]
    assert list(contact.threads.all()) == [fetched]
    assert list(user.owned_threads.all()) == [fetched]
    assert str(fetched) == "Rockefeller · engaged"


@pytest.mark.django_db
def test_activity_round_trip_and_newest_first_ordering(user):
    org = Organization.objects.create(name="Rockefeller")
    thread = OutreachThread.objects.create(org=org, owner=user)
    older = Activity.objects.create(
        thread=thread, activity_type="note", actor_type="human", actor=user
    )
    # force created_at apart so ordering is deterministic
    Activity.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
    newer = Activity.objects.create(
        thread=thread, activity_type="email_sent", actor_type="agent", agent_name="HERALD"
    )
    # ordered newest-first
    ordered = list(thread.activities.all())
    assert ordered[0] == newer
    assert ordered[-1].pk == older.pk
    # defaults
    assert newer.content_ref == {}
    assert newer.actor is None


@pytest.mark.django_db
def test_task_round_trip_and_defaults(user):
    org = Organization.objects.create(name="Rockefeller")
    thread = OutreachThread.objects.create(org=org, owner=user)
    task = Task.objects.create(
        thread=thread, owner=user, type="send_email", status="open"
    )
    fetched = Task.objects.get(pk=task.pk)
    assert fetched.thread == thread
    assert fetched.owner == user
    assert fetched.type == "send_email"
    assert fetched.status == "open"
    assert fetched.due is None
    assert fetched.drafted_content == ""
    assert fetched.gate_id == ""
    assert list(thread.tasks.all()) == [fetched]
    assert list(user.crm_tasks.all()) == [fetched]


@pytest.mark.django_db
def test_all_models_registered_in_admin():
    for model in (Organization, Contact, OutreachThread, Activity, Task):
        assert model in admin.site._registry
