"""Validates the seed_demo management command populates + wipes cleanly."""
import pytest
from django.core.management import call_command


@pytest.fixture
def owner(org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    return org_owner


@pytest.mark.django_db
def test_seed_demo_populates_and_is_idempotent(owner):
    from apps.crm.models import Activity, Contact, Organization, OutreachThread, Task
    from apps.joseph.models import CalendarEvent
    from apps.outreach.models import Mailbox, Sequence

    call_command("seed_demo", owner=owner.email)
    assert Organization.objects.count() >= 8
    assert Contact.objects.count() >= 8
    assert OutreachThread.objects.filter(owner=owner).count() >= 8
    assert OutreachThread.objects.filter(traffic_light="red").exists()       # action queue / red threads
    assert OutreachThread.objects.exclude(stage="wave1").count() >= 8        # real stages, not the Other column
    assert Activity.objects.exists() and Task.objects.exists()
    assert CalendarEvent.objects.count() >= 1                                 # Today strip
    assert Mailbox.objects.filter(user=owner).exists()
    assert Sequence.objects.count() >= 1

    # idempotent: re-run does not duplicate orgs/threads
    before = (Organization.objects.count(), OutreachThread.objects.count())
    call_command("seed_demo", owner=owner.email)
    assert (Organization.objects.count(), OutreachThread.objects.count()) == before


@pytest.mark.django_db
def test_seed_demo_wipe(owner):
    from apps.crm.models import Organization
    call_command("seed_demo", owner=owner.email)
    call_command("seed_demo", wipe=True)
    assert Organization.objects.filter(notes__contains="demo-seed").count() == 0
