import pytest
from django.utils import timezone
from datetime import timedelta


@pytest.mark.django_db
def test_deletion_purges_when_due(organization):
    from apps.organizations.models import Organization
    from apps.organizations.tasks import execute_scheduled_org_deletion

    org = organization
    org.deletion_requested_at = timezone.now()
    org.deletion_scheduled_for = timezone.now() - timedelta(minutes=1)
    org.save()

    execute_scheduled_org_deletion(org.id)
    assert not Organization.objects.filter(pk=org.id).exists()


@pytest.mark.django_db
def test_deletion_skips_when_future(organization):
    from apps.organizations.models import Organization
    from apps.organizations.tasks import execute_scheduled_org_deletion

    org = organization
    org.deletion_requested_at = timezone.now()
    org.deletion_scheduled_for = timezone.now() + timedelta(days=1)
    org.save()

    execute_scheduled_org_deletion(org.id)
    assert Organization.objects.filter(pk=org.id).exists()


# --- sweep task tests -------------------------------------------------------

@pytest.mark.django_db
def test_sweep_purges_overdue_orgs(organization):
    """sweep_scheduled_org_deletions deletes orgs whose eta has passed."""
    from apps.organizations.models import Organization
    from apps.organizations.tasks import sweep_scheduled_org_deletions

    org = organization
    org.deletion_requested_at = timezone.now() - timedelta(days=15)
    org.deletion_scheduled_for = timezone.now() - timedelta(days=1)
    org.save()

    sweep_scheduled_org_deletions()
    assert not Organization.objects.filter(pk=org.id).exists()


@pytest.mark.django_db
def test_sweep_skips_future_orgs(organization):
    """sweep_scheduled_org_deletions does not touch orgs still in grace period."""
    from apps.organizations.models import Organization
    from apps.organizations.tasks import sweep_scheduled_org_deletions

    org = organization
    org.deletion_requested_at = timezone.now()
    org.deletion_scheduled_for = timezone.now() + timedelta(days=13)
    org.save()

    sweep_scheduled_org_deletions()
    assert Organization.objects.filter(pk=org.id).exists()


@pytest.mark.django_db
def test_sweep_skips_orgs_without_deletion_flag(organization):
    """sweep_scheduled_org_deletions ignores normal orgs with no pending deletion."""
    from apps.organizations.models import Organization
    from apps.organizations.tasks import sweep_scheduled_org_deletions

    org = organization  # deletion_requested_at is None by default
    sweep_scheduled_org_deletions()
    assert Organization.objects.filter(pk=org.id).exists()


def test_sweep_registered_in_beat_schedule():
    """sweep-scheduled-org-deletions entry is present in BEAT_SCHEDULE."""
    from jobs.schedules import BEAT_SCHEDULE

    assert "sweep-scheduled-org-deletions" in BEAT_SCHEDULE
    entry = BEAT_SCHEDULE["sweep-scheduled-org-deletions"]
    assert entry["task"] == "apps.organizations.tasks.sweep_scheduled_org_deletions"
    # runs at most once per day — schedule run_every must be <= 86400 seconds
    assert entry["schedule"].run_every.total_seconds() <= 86400
