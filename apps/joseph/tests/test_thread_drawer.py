"""Tests for Joseph's thread drawer at /joseph/thread/<pk>/.

The CRM is now canonical in Django (the strangler step), so the drawer resolves a
local ``apps.crm.OutreachThread`` by its Django pk. The drawer is the full
operational view of a single deal thread: a header (org + stage + score +
traffic-light) with actions (Request deck / Capture → stubs, Escalate → creates a
notification), and six HTMX-swappable tabs (Brief / Timeline / Intelligence /
Tasks / Deck / Sequence). The Brief tab maps the Django thread + its dossier
(``readers.get_dossier(dossier_id)``) onto the L0 card; the Intelligence tab pulls
the wiki page for the org plus org-filtered news; the Timeline/Tasks tabs read the
CRM Activity/Task log; Deck/Sequence are present-but-stubbed.

The view is gated by ``_can_access_joseph`` and degrades gracefully when the
agent-service is down (the dossier/wiki reads return safe defaults — never a 500).
CSP-safe: tab switching is HTMX (hx-get), no inline onclick/onsubmit.
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


DOSSIER = {
    "id": "d1",
    "entity": "Rockefeller Foundation",
    "summary": "Closing a $500M Africa climate window this quarter.",
    "body_md": "## Overview\nLong-form dossier body.",
    "sources": [{"ref": "s1", "trust": 0.9}],
    "red_flags": ["Slow legal"],
    "hooks": {"climate": "Lead with the SE4ALL precedent."},
    "meta": {"warm_path": "Intro via Dr. Shah's chief of staff."},
    "updated_at": "2026-06-14T10:00:00Z",
    "status": "ready",
    "thread_id": "d1",
}


@pytest.fixture
def crm_thread(db):
    """A local CRM thread (org + contact + dossier_id + a logged activity)."""
    from apps.crm.models import Activity, Contact, Organization, OutreachThread

    org = Organization.objects.create(name="Rockefeller Foundation")
    contact = Contact.objects.create(
        org=org, full_name="Dr. Rajiv Shah", role="President",
    )
    t = OutreachThread.objects.create(
        org=org, primary_contact=contact, track="climate",
        stage=OutreachThread.Stage.PROPOSAL, traffic_light="red",
        quintile=4, score=0.71, next_action="deck opened", dossier_id="d1",
    )
    Activity.objects.create(
        thread=t, activity_type="note", actor_type="human",
        content_ref={"body": "Deck opened by the President's office."},
    )
    return t


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
    """An ordinary workspace member (viewer) — must not reach the drawer."""
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


# --------------------------------------------------------------------------
# header / shell
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_drawer_header_shows_org_stage_score(joseph, client, crm_thread):
    """The drawer header surfaces org + stage + score."""
    with patch("apps.joseph.intelligence.readers.get_dossier", return_value=DOSSIER):
        resp = client.get(reverse("joseph:thread", args=[crm_thread.id]))
    assert resp.status_code == 200
    body = resp.content
    assert b"Rockefeller Foundation" in body
    assert b"Proposal" in body or b"proposal" in body
    assert b"0.71" in body


@pytest.mark.django_db
def test_drawer_renders_all_six_tabs(joseph, client, crm_thread):
    """The drawer shell exposes all six tabs."""
    with patch("apps.joseph.intelligence.readers.get_dossier", return_value=DOSSIER):
        resp = client.get(reverse("joseph:thread", args=[crm_thread.id]))
    body = resp.content
    for tab in (b"Brief", b"Timeline", b"Intelligence", b"Tasks", b"Deck", b"Sequence"):
        assert tab in body


@pytest.mark.django_db
def test_drawer_header_has_actions(joseph, client, crm_thread):
    """Header actions: Request deck / Capture (stubs) + Escalate."""
    with patch("apps.joseph.intelligence.readers.get_dossier", return_value=DOSSIER):
        resp = client.get(reverse("joseph:thread", args=[crm_thread.id]))
    body = resp.content
    assert b"Request deck" in body
    assert b"Capture" in body
    assert b"Escalate" in body


@pytest.mark.django_db
def test_drawer_forbidden_for_viewer(viewer, client, crm_thread):
    """A non-owner/admin/principal member must not reach the drawer."""
    resp = client.get(reverse("joseph:thread", args=[crm_thread.id]))
    assert resp.status_code in (403, 302)


@pytest.mark.django_db
def test_drawer_agent_down_renders_no_500(joseph, client, crm_thread):
    """Agent-service down → the dossier read swallows AgentClientError → safe
    defaults → a 200 page, never a 500. (The thread itself is local Django.)"""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        resp = client.get(reverse("joseph:thread", args=[crm_thread.id]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_drawer_csp_safe_no_inline_handlers(joseph, client, crm_thread):
    """The drawer is CSP-safe: HTMX tab switching, no inline onclick/onsubmit."""
    with patch("apps.joseph.intelligence.readers.get_dossier", return_value=DOSSIER):
        resp = client.get(reverse("joseph:thread", args=[crm_thread.id]))
    body = resp.content
    assert b"hx-get" in body
    assert b"onclick=" not in body
    assert b"onsubmit=" not in body


# --------------------------------------------------------------------------
# tabs (HTMX partials)
# --------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("tab", ["brief", "timeline", "intelligence", "tasks", "deck", "sequence"])
def test_drawer_tab_returns_200(joseph, client, crm_thread, tab):
    """Every tab param returns 200 as an HTMX partial."""
    with patch("apps.joseph.intelligence.readers.get_dossier", return_value=DOSSIER), \
         patch("apps.joseph.views.readers.get_page", return_value={}), \
         patch("apps.joseph.views.readers.news_about", return_value=[]):
        resp = client.get(
            reverse("joseph:thread", args=[crm_thread.id]) + f"?tab={tab}",
            HTTP_HX_REQUEST="true",
        )
    assert resp.status_code == 200
    # HTMX partial must NOT re-render the whole page chrome.
    assert b"<html" not in resp.content.lower()


@pytest.mark.django_db
def test_drawer_brief_tab_reuses_l0_card(joseph, client, crm_thread):
    """The Brief tab reuses the L0 card (the six editorial fields)."""
    with patch("apps.joseph.intelligence.readers.get_dossier", return_value=DOSSIER):
        resp = client.get(
            reverse("joseph:thread", args=[crm_thread.id]) + "?tab=brief",
            HTTP_HX_REQUEST="true",
        )
    body = resp.content
    assert b"WHO" in body
    assert b"WHY NOW" in body
    assert b"RED FLAGS" in body
    assert b"Dr. Rajiv Shah" in body


@pytest.mark.django_db
def test_drawer_intelligence_tab_pulls_wiki_and_news(joseph, client, crm_thread):
    """The Intelligence tab pulls the wiki page for the org + news_about(org)."""
    page = {"slug": "rockefeller-foundation", "title": "Rockefeller Foundation",
            "tier": "l1", "content": "WIKI OVERVIEW BODY"}
    news = [{"title": "Rockefeller launches climate fund", "summary": "..."}]
    with patch("apps.joseph.views.readers.get_page", return_value=page) as gp, \
         patch("apps.joseph.views.readers.news_about", return_value=news) as na:
        resp = client.get(
            reverse("joseph:thread", args=[crm_thread.id]) + "?tab=intelligence",
            HTTP_HX_REQUEST="true",
        )
    assert resp.status_code == 200
    body = resp.content
    assert b"WIKI OVERVIEW BODY" in body
    assert b"Rockefeller launches climate fund" in body
    gp.assert_called_once()
    na.assert_called_once_with("Rockefeller Foundation")


@pytest.mark.django_db
def test_drawer_deck_tab_is_stubbed(joseph, client, crm_thread):
    """The Deck tab is present-but-stubbed (coming in a later phase)."""
    resp = client.get(
        reverse("joseph:thread", args=[crm_thread.id]) + "?tab=deck",
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert b"coming" in resp.content.lower()


@pytest.mark.django_db
def test_drawer_sequence_tab_shows_outreach_surfaces(joseph, client, crm_thread):
    """The Sequence tab is live (Phase 2C): the gate-checked send form + the
    sequence enroll/timeline panel mount here, posting to the outreach views."""
    resp = client.get(
        reverse("joseph:thread", args=[crm_thread.id]) + "?tab=sequence",
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    # The send form posts to the gated thread-send endpoint, the panel to enroll.
    assert f"/outreach/threads/{crm_thread.id}/send/" in body
    assert f"/outreach/threads/{crm_thread.id}/enroll/" in body
    # CSP-safe — no inline handlers.
    assert "onclick=" not in body
    assert "onsubmit=" not in body


@pytest.mark.django_db
def test_drawer_timeline_tab_shows_activity(joseph, client, crm_thread):
    """The Timeline tab renders the CRM Activity log for the thread."""
    resp = client.get(
        reverse("joseph:thread", args=[crm_thread.id]) + "?tab=timeline",
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    assert b"Deck opened by the President" in resp.content


@pytest.mark.django_db
def test_drawer_unknown_tab_falls_back_to_brief(joseph, client, crm_thread):
    """An unrecognised ?tab= never 500s — it falls back to the Brief tab."""
    with patch("apps.joseph.intelligence.readers.get_dossier", return_value=DOSSIER):
        resp = client.get(
            reverse("joseph:thread", args=[crm_thread.id]) + "?tab=bogus",
            HTTP_HX_REQUEST="true",
        )
    assert resp.status_code == 200
    assert b"WHO" in resp.content


# --------------------------------------------------------------------------
# escalate (POST → create notification)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_escalate_creates_notification(joseph, client, crm_thread):
    """POST .../escalate/ creates a notification via readers and returns ok."""
    with patch("apps.joseph.views.readers.create_notification",
               return_value={"id": "n1"}) as cn:
        resp = client.post(reverse("joseph:thread-escalate", args=[crm_thread.id]))
    assert resp.status_code in (200, 302, 303)
    cn.assert_called_once()
    # the thread id is carried into the notification create call
    assert str(crm_thread.id) in str(cn.call_args)


@pytest.mark.django_db
def test_escalate_forbidden_for_viewer(viewer, client, crm_thread):
    """A viewer cannot escalate; the agent-service must not be hit."""
    with patch("apps.joseph.views.readers.create_notification") as cn:
        resp = client.post(reverse("joseph:thread-escalate", args=[crm_thread.id]))
    assert resp.status_code in (403, 302)
    cn.assert_not_called()


@pytest.mark.django_db
def test_escalate_agent_down_no_500(joseph, client, crm_thread):
    """Agent-service down → create_notification swallows the error → no 500."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_post", side_effect=AgentClientError("down")):
        resp = client.post(reverse("joseph:thread-escalate", args=[crm_thread.id]))
    assert resp.status_code in (200, 302, 303)
