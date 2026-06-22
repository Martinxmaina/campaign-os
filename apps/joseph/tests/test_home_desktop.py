"""Tests for Joseph's DESKTOP home — the operational surface at /joseph/?view=desktop.

The desktop home is the full operations shell (extends the real console
``base.html`` so it inherits the Campaign OS sidebar). On top of the shared
home data it adds three operational surfaces fleshed out in Task 7:

  * a content-pipeline summary — created (composer Posts) + curated
    (ContentIntake) content de-duped onto one funnel with a % through it,
    read from the canonical Django tables (``content_pipeline_progress``);
  * an escalations strip — the urgent slice of ``JosephIntelligence.proposals()``;
  * the action queue — the full proposals merge.

Like every Joseph view it is gated by ``_can_access_joseph`` and degrades
gracefully when the agent-service is down (empty states, never a 500).
"""
from unittest.mock import patch

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
    """An ordinary workspace member (viewer) — must not reach Joseph's surface."""
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


def _desktop(client):
    return client.get(reverse("joseph:home") + "?view=desktop")


@pytest.mark.django_db
def test_desktop_home_uses_desktop_template_and_real_sidebar(joseph, client):
    """The desktop surface renders home_desktop.html, which extends the real
    console base.html (so it inherits the Campaign OS sidebar + chrome)."""
    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.views.readers.list_content", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = _desktop(client)
    assert resp.status_code == 200
    names = [t.name for t in resp.templates if t.name]
    assert "joseph/home_desktop.html" in names
    assert "base.html" in names


@pytest.mark.django_db
def test_desktop_home_shows_content_pipeline_progress(joseph, client, workspace):
    """The Content pipeline widget summarises created (composer Posts) + curated
    (ContentIntake) content as one funnel, with a % through the pipeline. Read
    from the canonical Django tables, not the agent-service."""
    from apps.composer.models import Post
    from apps.content_intake.models import ContentIntake
    ContentIntake.objects.create(
        workspace=workspace, external_id="p1", status=ContentIntake.Status.PUBLISHED)
    ContentIntake.objects.create(
        workspace=workspace, external_id="c1", status=ContentIntake.Status.ACCEPTED)
    Post.objects.create(workspace=workspace, caption="standalone draft")  # created

    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = _desktop(client)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Content pipeline" in body
    assert "through pipeline" in body  # the weighted progress label
    # unified funnel stage labels are present
    for label in ("Curated", "Drafting", "Published"):
        assert label in body
    # 3 pieces total (2 curated + 1 created), 1 published
    assert "3" in body


@pytest.mark.django_db
def test_desktop_home_shows_pipeline_by_track(joseph, client):
    """The desktop home shows a "Pipeline by track" panel grouping local CRM
    threads by track (real counts, not a fabricated dollar funnel)."""
    from apps.crm.models import Organization, OutreachThread
    for org_name, track in [("GEAPP", "ai10bn"), ("AI-x", "ai10bn"), ("GIZ", "core")]:
        org = Organization.objects.create(name=org_name)
        OutreachThread.objects.create(org=org, track=track)
    with patch("apps.joseph.views.readers.list_content", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = _desktop(client)
    assert resp.status_code == 200
    body = resp.content
    assert b"Pipeline by track" in body
    assert b"AI 10Bn" in body and b"Core programs" in body
    assert b">2<" in body  # ai10bn count


@pytest.mark.django_db
def test_desktop_home_shows_escalations_strip(joseph, client):
    """Urgent proposals surface in a dedicated escalations strip; non-urgent ones
    do not appear there (they live only in the action queue)."""
    urgent = {"id": "n1", "kind": "gate_flag", "body": "Gate block on AfDB post",
              "urgent": True, "action": {"href": "/x"}}
    calm = {"id": "n2", "kind": "fyi", "body": "Routine digest ready",
            "urgent": False, "action": {"href": "/y"}}
    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.views.readers.list_content", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[urgent, calm]):
        resp = _desktop(client)
    assert resp.status_code == 200
    body = resp.content
    assert b"Escalations" in body or b"ESCALATIONS" in body
    # the urgent one is in the escalations strip
    assert b"Gate block on AfDB post" in body


@pytest.mark.django_db
def test_desktop_home_no_escalations_shows_empty_state(joseph, client):
    """With no urgent proposals the escalations strip renders a calm empty state,
    not a 500 and not a phantom urgent row."""
    calm = {"id": "n2", "kind": "fyi", "body": "Routine digest ready",
            "urgent": False, "action": {"href": "/y"}}
    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.views.readers.list_content", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[calm]):
        resp = _desktop(client)
    assert resp.status_code == 200
    assert b"Escalations" in resp.content or b"ESCALATIONS" in resp.content


@pytest.mark.django_db
def test_desktop_home_shows_action_queue(joseph, client):
    """The full action queue (proposals merge) is present on the desktop home."""
    notif = {"id": "n1", "kind": "deck_ready", "body": "GEAPP deck ready",
             "urgent": False, "action": {"href": "/z"}}
    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.views.readers.list_content", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[notif]):
        resp = _desktop(client)
    assert resp.status_code == 200
    body = resp.content
    assert b"Action queue" in body or b"ACTION QUEUE" in body
    assert b"GEAPP deck ready" in body


@pytest.mark.django_db
def test_desktop_home_forbidden_for_viewer(viewer, client):
    """A non-owner/admin/principal member must not reach the desktop surface; the
    agent-service must not be hit at all."""
    with patch("apps.joseph.views.readers.list_threads") as lt, \
         patch("apps.joseph.views.readers.list_content") as lc:
        resp = _desktop(client)
    assert resp.status_code in (403, 302)
    lt.assert_not_called()
    lc.assert_not_called()


@pytest.mark.django_db
def test_desktop_home_agent_down_renders_empty_state_no_500(joseph, client):
    """Agent-service down → the real readers swallow AgentClientError and return
    safe defaults → the desktop home renders a 200 empty state, never a 500.

    Patches the underlying agent_get/agent_post so the genuine degrade path runs
    end-to-end (funnel counts fall back to 0, escalations + queue empty)."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")), \
         patch("apps.joseph.readers.agent_post", side_effect=AgentClientError("down")):
        resp = _desktop(client)
    assert resp.status_code == 200
    body = resp.content
    assert b"Content pipeline" in body
    assert b"Pipeline by track" in body
    assert b"Escalations" in body or b"ESCALATIONS" in body
    assert b"Action queue" in body or b"ACTION QUEUE" in body


@pytest.mark.django_db
def test_desktop_home_csp_safe_no_inline_handlers(joseph, client):
    """The desktop home is CSP-safe — no inline onclick/onsubmit handlers."""
    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.views.readers.list_content", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = _desktop(client)
    assert b"onclick=" not in resp.content
    assert b"onsubmit=" not in resp.content


@pytest.mark.django_db
def test_desktop_home_renders_branded_hero_header(joseph, client):
    """T3 uplift: the desktop home opens with a branded hero band (the approved
    preview's editorial header) — a distinct ``joseph-hero`` wrapper carrying the
    Georgia greeting + the headline stat row — not the old plain ``h1``. Existing
    operational surfaces (This week, Content pipeline, Action queue) stay intact."""
    with patch("apps.joseph.views.readers.list_threads", return_value=[]), \
         patch("apps.joseph.views.readers.list_content", return_value=[]), \
         patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = _desktop(client)
    assert resp.status_code == 200
    body = resp.content
    # the new hero wrapper marker
    assert b"joseph-hero" in body
    # the editorial greeting still lives inside it (Georgia font-display)
    assert b"font-display" in body
    assert b"Good day, Joseph" in body
    # operational surfaces untouched by the styling pass
    assert b"This week" in body
    assert b"Content pipeline" in body
    assert b"Action queue" in body or b"ACTION QUEUE" in body
