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


@pytest.mark.django_db
def test_ambiguous_substring_prefers_exact_name(workspace):
    """A bare first name like 'Joseph' must NOT be routed to 'Josephine Other'.

    Both names contain the substring 'Joseph', so a loose icontains+.first()
    lookup returns an arbitrary row depending on DB order. Exact-name matching
    must win deterministically — and must hold regardless of insertion order.
    """
    # Insert the decoy FIRST so a naive icontains+.first() would return it.
    josephine = _user("josephine@afcen.org", "Josephine Other", workspace)
    joseph = _user("joseph@afcen.org", "Joseph", workspace)
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-5",
        pillar_theme="AI", owner_raw="Joseph", sensitivity="public_safe", status="accepted")
    resolved = resolve_reviewer(item)
    assert resolved == joseph
    assert resolved != josephine


@pytest.mark.django_db
def test_pillar_fallback_substring_does_not_misroute(workspace):
    """Pillar fallback also looks up a bare first name ('Joseph' for AI). The
    same exact-match determinism must protect that path."""
    josephine = _user("josephine@afcen.org", "Josephine Other", workspace)
    joseph = _user("joseph@afcen.org", "Joseph", workspace)
    # owner_raw empty → falls through to the pillar owner ('Joseph' for AI).
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-6",
        pillar_theme="AI", owner_raw="", sensitivity="public_safe", status="accepted")
    resolved = resolve_reviewer(item)
    assert resolved == joseph
    assert resolved != josephine


@pytest.mark.django_db
def test_energy_and_minerals_both_route_to_dennis(workspace):
    """Two pillars map to the same owner; both must resolve to that user."""
    dennis = _user("dennis@afcen.org", "Dennis Mwangi", workspace)
    energy = ContentIntake.objects.create(workspace=workspace, external_id="O-7",
        pillar_theme="Energy", owner_raw="", sensitivity="public_safe", status="accepted")
    minerals = ContentIntake.objects.create(workspace=workspace, external_id="O-8",
        pillar_theme="Minerals", owner_raw="", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(energy) == dennis
    assert resolve_reviewer(minerals) == dennis


@pytest.mark.django_db
def test_does_not_match_user_in_other_workspace(workspace):
    """Cross-house wall: a matching member in a DIFFERENT workspace must NOT be
    returned. Routing is scoped strictly to the intake's own workspace."""
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace

    other_org = Organization.objects.create(name="Other Org")
    other_ws = Workspace.objects.create(organization=other_org, name="Other House")
    # Carren exists, but only in the OTHER workspace.
    _user("carren@afcen.org", "Carren Atieno", other_ws)
    # The intake belongs to `workspace`, which has no Carren and no owner/admin.
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-9",
        pillar_theme="Agribusiness", owner_raw="Carren", sensitivity="public_safe", status="accepted")
    assert resolve_reviewer(item) is None


@pytest.mark.django_db
def test_resolve_reviewer_is_wired_into_draft_creation(workspace):
    """resolve_reviewer must have a real runtime effect: drafting an intake
    files a SUBMITTED ApprovalAction assigned to the resolved reviewer."""
    from unittest.mock import patch
    from apps.content_intake.draft_post import ensure_draft_post
    from apps.approvals.models import ApprovalAction

    dennis = _user("dennis@afcen.org", "Dennis Mwangi", workspace)
    item = ContentIntake.objects.create(workspace=workspace, external_id="O-10",
        pillar_theme="Energy", angle="Solar", owner_raw="",
        sensitivity="public_safe", status="drafting")
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        post = ensure_draft_post(item)

    action = ApprovalAction.objects.get(post=post)
    assert action.user == dennis
    assert action.action == ApprovalAction.ActionType.SUBMITTED

    # Re-ensuring the draft must not file a duplicate submission (idempotent).
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        ensure_draft_post(item)
    assert ApprovalAction.objects.filter(post=post).count() == 1


@pytest.mark.django_db
def test_post_review_fields_default(workspace):
    from apps.composer.models import Post
    p = Post.objects.create(workspace=workspace, title="t", caption="c")
    assert p.review_assignee is None
    assert p.review_state == "none"
