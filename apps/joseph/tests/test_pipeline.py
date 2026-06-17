"""Tests for Joseph's pipeline kanban at /joseph/pipeline/.

The CRM is now canonical in Django (the first strangler step), so the pipeline
groups ``apps.crm.OutreachThread`` rows from the LOCAL database into stage
columns (discover, qualify, proposal, diligence, committed + a catch-all) —
there is NO ``readers.list_threads`` HTTP call to agent-service. Each card shows
the org, a traffic-light dot (coloured from days-since-touch), the quintile, and
the next action. The view is gated by ``_can_access_joseph``.
"""
import pytest
from django.urls import reverse


@pytest.fixture
def joseph(client, org_owner, workspace):
    """Joseph = an owner of the workspace (can access the principal surface)."""
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def viewer(client, db, organization, workspace):
    """An ordinary workspace member (viewer) — must not reach the pipeline."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer", tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


def _make_thread(*, org_name, stage, traffic_light="green", quintile=0,
                 next_action="", track="", last_touch=None):
    """Create a CRM OutreachThread (+ its org) in the local DB."""
    from apps.crm.models import Organization, OutreachThread
    org, _ = Organization.objects.get_or_create(name=org_name)
    return OutreachThread.objects.create(
        org=org, stage=stage, traffic_light=traffic_light, quintile=quintile,
        next_action=next_action, track=track, last_touch=last_touch,
    )


@pytest.fixture
def seed_threads(db):
    """A spread of CRM threads across the pipeline stages."""
    _make_thread(org_name="GEAPP", stage="discover", traffic_light="amber",
                 quintile=4, next_action="deck —", track="AI 10Bn")
    _make_thread(org_name="GIZ", stage="qualify", traffic_light="green",
                 quintile=5, next_action="deck draft", track="bilateral TA")
    _make_thread(org_name="Rockefeller", stage="proposal", traffic_light="red",
                 quintile=4, next_action="deck opened", track="catalytic capital")
    _make_thread(org_name="Mission 300", stage="committed", traffic_light="green",
                 quintile=5, next_action="deck sent", track="energy access")


@pytest.mark.django_db
def test_pipeline_renders_stage_columns(joseph, client, seed_threads):
    """Threads are grouped into the five ordered stage columns."""
    resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code == 200
    body = resp.content
    for col in (b"Discover", b"Qualify", b"Proposal", b"Diligence", b"Committed"):
        assert col in body


@pytest.mark.django_db
def test_pipeline_card_shows_org_quintile_next_action(joseph, client, seed_threads):
    """A card surfaces the org, the quintile and the next action."""
    resp = client.get(reverse("joseph:pipeline"))
    body = resp.content
    assert b"Rockefeller" in body
    assert b"deck opened" in body
    assert b"catalytic capital" in body
    # quintile rendered (e.g. "Q4")
    assert b"Q4" in body
    assert b"Q5" in body


@pytest.mark.django_db
def test_pipeline_card_shows_days_since_touch_and_quintile_dots(joseph, client):
    """A card surfaces the days-since-touch chip (from last_touch) and the
    quintile dot-row (●●●●○) — matching the approved mockup."""
    from datetime import timedelta
    from django.utils import timezone
    _make_thread(
        org_name="GEAPP", stage="discover", traffic_light="amber", quintile=4,
        next_action="deck —", track="AI 10Bn",
        last_touch=timezone.now() - timedelta(days=9, hours=2),
    )
    resp = client.get(reverse("joseph:pipeline"))
    body = resp.content
    assert b"9d" in body                       # days-since-touch chip
    assert "●●●●○".encode() in body            # quintile-4 dot row


@pytest.mark.django_db
def test_pipeline_card_links_to_thread_drawer(joseph, client):
    """Each card links to the thread drawer at /joseph/thread/<pk>/."""
    t = _make_thread(org_name="Rockefeller", stage="proposal", traffic_light="red",
                     quintile=4, next_action="deck opened")
    resp = client.get(reverse("joseph:pipeline"))
    assert f"/joseph/thread/{t.id}/".encode() in resp.content


@pytest.mark.django_db
def test_pipeline_card_has_traffic_light_dot(joseph, client, seed_threads):
    """A card renders a traffic-light dot coloured per status."""
    resp = client.get(reverse("joseph:pipeline"))
    body = resp.content
    # the red proposal thread paints an error dot
    assert b"var(--error)" in body
    # the green committed thread paints a success dot
    assert b"var(--success)" in body


@pytest.mark.django_db
def test_pipeline_forbidden_for_viewer(viewer, client):
    """A non-owner/admin/principal member must not reach the pipeline."""
    resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code in (403, 302)


@pytest.mark.django_db
def test_pipeline_reads_local_db_not_agent_service(joseph, client, seed_threads):
    """The pipeline groups local CRM threads — it never calls agent-service
    (no ``readers.list_threads`` / ``agent_get`` HTTP read)."""
    from unittest.mock import patch
    with patch("apps.common.agent_client.agent_get") as ag:
        resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code == 200
    assert b"Rockefeller" in resp.content
    ag.assert_not_called()


@pytest.mark.django_db
def test_pipeline_empty_renders_empty_columns_no_500(joseph, client):
    """No threads → the stage columns still render (empty), never a 500."""
    resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code == 200
    assert b"Discover" in resp.content
    assert b"Committed" in resp.content


@pytest.mark.django_db
def test_pipeline_unknown_stage_falls_into_catch_all(joseph, client):
    """A thread with an unrecognised stage is not dropped — it lands in a
    catch-all column so nothing silently disappears from the board."""
    _make_thread(org_name="Mystery Co", stage="targeted", traffic_light="amber",
                 quintile=3, next_action="?")
    resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code == 200
    assert b"Mystery Co" in resp.content


@pytest.mark.django_db
def test_pipeline_is_the_principal_board(joseph, client, seed_threads):
    """/joseph/pipeline is the principal board: a 'My pipeline' header (his lens),
    NOT the console's 'Team pipeline', and the cards carry NO Owner badge (it's
    all his)."""
    resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "My pipeline" in body
    assert "Team pipeline" not in body
    # No per-card Owner badge on the principal lens.
    assert "Owner" not in body


@pytest.mark.django_db
def test_pipeline_csp_safe_no_inline_handlers(joseph, client, seed_threads):
    """The board is CSP-safe — no inline onclick/onsubmit handlers."""
    resp = client.get(reverse("joseph:pipeline"))
    assert b"onclick=" not in resp.content
    assert b"onsubmit=" not in resp.content
