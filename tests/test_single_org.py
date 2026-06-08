import pytest
from django.urls import reverse, NoReverseMatch


@pytest.mark.django_db
def test_default_org_and_workspace_seeded():
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace
    assert Organization.objects.count() == 1
    assert Workspace.objects.count() >= 1


def test_billing_and_client_portal_routes_removed():
    for name in ["client_portal:index", "intelligence:checkout"]:
        with pytest.raises(NoReverseMatch):
            reverse(name)
