"""Tests for Joseph's pipeline kanban at /joseph/pipeline/.

The pipeline groups agent-service threads into stage columns (discover, qualify,
proposal, diligence, committed + a catch-all), and each card shows the org, a
traffic-light dot (coloured from days-since-touch), the quintile, and the next
action. The view is gated by ``_can_access_joseph`` and degrades gracefully when
the agent-service is down (empty columns, never a 500).
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


THREADS = [
    {"id": "t-disc", "org": "GEAPP", "stage": "discover", "traffic_light": "amber",
     "quintile": 4, "next_action": "deck —", "track": "AI 10Bn"},
    {"id": "t-qual", "org": "GIZ", "stage": "qualify", "traffic_light": "green",
     "quintile": 5, "next_action": "deck draft", "track": "bilateral TA"},
    {"id": "t-prop", "org": "Rockefeller", "stage": "proposal", "traffic_light": "red",
     "quintile": 4, "next_action": "deck opened", "track": "catalytic capital"},
    {"id": "t-comm", "org": "Mission 300", "stage": "committed", "traffic_light": "green",
     "quintile": 5, "next_action": "deck sent", "track": "energy access"},
]


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


@pytest.mark.django_db
def test_pipeline_renders_stage_columns(joseph, client):
    """Threads are grouped into the five ordered stage columns."""
    with patch("apps.joseph.views.readers.list_threads", return_value=THREADS):
        resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code == 200
    body = resp.content
    for col in (b"Discover", b"Qualify", b"Proposal", b"Diligence", b"Committed"):
        assert col in body


@pytest.mark.django_db
def test_pipeline_card_shows_org_quintile_next_action(joseph, client):
    """A card surfaces the org, the quintile and the next action."""
    with patch("apps.joseph.views.readers.list_threads", return_value=THREADS):
        resp = client.get(reverse("joseph:pipeline"))
    body = resp.content
    assert b"Rockefeller" in body
    assert b"deck opened" in body
    assert b"catalytic capital" in body
    # quintile rendered (e.g. "Q4")
    assert b"Q4" in body
    assert b"Q5" in body


@pytest.mark.django_db
def test_pipeline_card_links_to_thread_drawer(joseph, client):
    """Each card links to the thread drawer at /joseph/thread/<id>/ (Task 6)."""
    with patch("apps.joseph.views.readers.list_threads", return_value=THREADS):
        resp = client.get(reverse("joseph:pipeline"))
    assert b"/joseph/thread/t-prop/" in resp.content


@pytest.mark.django_db
def test_pipeline_card_has_traffic_light_dot(joseph, client):
    """A card renders a traffic-light dot coloured per status."""
    with patch("apps.joseph.views.readers.list_threads", return_value=THREADS):
        resp = client.get(reverse("joseph:pipeline"))
    body = resp.content
    # the red proposal thread paints an error dot
    assert b"var(--error)" in body
    # the green committed thread paints a success dot
    assert b"var(--success)" in body


@pytest.mark.django_db
def test_pipeline_forbidden_for_viewer(viewer, client):
    """A non-owner/admin/principal member must not reach the pipeline; the
    agent-service must not be hit at all."""
    with patch("apps.joseph.views.readers.list_threads") as lt:
        resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code in (403, 302)
    lt.assert_not_called()


@pytest.mark.django_db
def test_pipeline_agent_down_renders_empty_columns_no_500(joseph, client):
    """Agent-service down → readers swallow AgentClientError and return [] →
    the pipeline renders 200 with empty columns, never a 500."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code == 200
    # the stage columns still render (empty)
    assert b"Discover" in resp.content
    assert b"Committed" in resp.content


@pytest.mark.django_db
def test_pipeline_unknown_stage_falls_into_catch_all(joseph, client):
    """A thread with an unrecognised stage is not dropped — it lands in a
    catch-all column so nothing silently disappears from the board."""
    threads = [{"id": "t-x", "org": "Mystery Co", "stage": "ghost",
                "traffic_light": "amber", "quintile": 3, "next_action": "?"}]
    with patch("apps.joseph.views.readers.list_threads", return_value=threads):
        resp = client.get(reverse("joseph:pipeline"))
    assert resp.status_code == 200
    assert b"Mystery Co" in resp.content


@pytest.mark.django_db
def test_pipeline_csp_safe_no_inline_handlers(joseph, client):
    """The board is CSP-safe — no inline onclick/onsubmit handlers."""
    with patch("apps.joseph.views.readers.list_threads", return_value=THREADS):
        resp = client.get(reverse("joseph:pipeline"))
    assert b"onclick=" not in resp.content
    assert b"onsubmit=" not in resp.content
