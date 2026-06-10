import pytest
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace
from datetime import date, timedelta


@pytest.fixture
def workspace(db):
    org = Organization.objects.create(name="AfCEN Test")
    return Workspace.objects.create(organization=org, name="WAIIS")


@pytest.fixture
def intake_item(db, workspace):
    from apps.content_intake.models import ContentIntake

    return ContentIntake.objects.create(
        workspace=workspace,
        external_id="TEST-001",
        pillar_theme="Energy",
        angle="Solar growth",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
        priority=ContentIntake.Priority.HIGH,
    )


@pytest.fixture
def intake_item_with_date(db, workspace):
    from apps.content_intake.models import ContentIntake

    return ContentIntake.objects.create(
        workspace=workspace,
        external_id="TEST-DATE-001",
        pillar_theme="AI",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
        target_publish_date=date.today() + timedelta(days=7),
    )
