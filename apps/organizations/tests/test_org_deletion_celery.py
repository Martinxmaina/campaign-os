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
