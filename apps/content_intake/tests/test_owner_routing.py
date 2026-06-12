# apps/content_intake/tests/test_owner_routing.py
import pytest
from apps.content_intake.owner_routing import resolve_reviewer
from apps.content_intake.models import ContentIntake


def _user(email, name, workspace, role="member"):
    from django.contrib.auth import get_user_model
    from apps.members.models import WorkspaceMembership
    u = get_user_model().objects.create_user(email=email, password="pw12345678", name=name)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role=role)
    return u


@pytest.mark.django_db
def test_matches_owner_raw_by_name(workspace):
    carren = _user("carren@afcen.org", "Carren Atieno", workspace)
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-1",
        pillar_theme="Agribusiness", owner_raw="Carren", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(item) == carren


@pytest.mark.django_db
def test_falls_back_to_pillar_owner(workspace):
    dennis = _user("dennis@afcen.org", "Dennis Mwangi", workspace)
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-2",
        pillar_theme="Energy", owner_raw="", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(item) == dennis


@pytest.mark.django_db
def test_falls_back_to_workspace_owner_when_unmapped(workspace):
    boss = _user("boss@afcen.org", "Boss Lady", workspace, role="owner")
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-3",
        pillar_theme="Totally Unknown Pillar", owner_raw="Nobody", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(item) == boss


@pytest.mark.django_db
def test_returns_none_when_no_owner_exists(workspace):
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-4",
        pillar_theme="X", owner_raw="Y", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(item) is None
