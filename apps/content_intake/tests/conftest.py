import pytest
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


@pytest.fixture
def workspace(db):
    org = Organization.objects.create(name="AfCEN Test")
    return Workspace.objects.create(organization=org, name="WAIIS")
