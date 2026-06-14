"""The dossier-refresh action (Task 9 — the seam flip, Django side).

The CRM is canonical in Django. To refresh a thread's dossier the team POSTs
``/crm/threads/<id>/refresh-dossier/``; Django builds the thread's *context*
(entity/org/contact/track) and posts it to the agent-service compile seam
(``readers.compile_dossier_with_context`` → ``POST /agents/dossier/compile``).
The returned ``dossier_id`` is stored back on the local ``OutreachThread``.

agent-service is mocked here — no live intelligence call. The action is gated by
``_can_manage_crm`` and degrades quietly when the agent-service is down (the
reader swallows ``AgentClientError`` → ``{}`` → no dossier_id written, no 500).
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


# ---------------------------------------------------------------------------
# Role fixtures (mirror test_thread_actions.py) — manager passes, viewer 403s.
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership

    WorkspaceMembership.objects.create(
        user=org_owner, workspace=workspace, workspace_role="owner"
    )
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def viewer(client, db, organization, workspace):
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from django.utils import timezone

    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer",
        tos_accepted_at=timezone.now(),
    )
    OrgMembership.objects.create(
        user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER
    )
    WorkspaceMembership.objects.create(
        user=u, workspace=workspace, workspace_role="member"
    )
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


@pytest.fixture
def thread(db):
    from apps.crm.models import Contact, Organization, OutreachThread

    org = Organization.objects.create(
        name="Rockefeller Foundation",
        type=Organization.Type.FUNDER,
        tier=Organization.Tier.T1,
        track_tags=["ai10bn"],
    )
    okonkwo = Contact.objects.create(
        org=org, full_name="Dr. Okonkwo",
        seniority=Contact.Seniority.VP, email="okonkwo@rockefeller.org",
    )
    return OutreachThread.objects.create(
        org=org, primary_contact=okonkwo, stage=OutreachThread.Stage.ENGAGED,
        track="ai10bn", traffic_light="amber", quintile=4, score=0.7,
        dossier_id="",
    )


# ---------------------------------------------------------------------------
# readers.compile_dossier_with_context — posts the context to the seam.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compile_dossier_with_context_posts_to_seam():
    from apps.joseph import readers

    payload = {"entity": "Rockefeller Foundation", "org": "Rockefeller Foundation",
               "contact": "Dr. Okonkwo", "track": "ai10bn"}
    with patch("apps.joseph.readers.agent_post") as ap:
        ap.return_value = {"dossier_id": "d-new", "sources": 3}
        out = readers.compile_dossier_with_context(payload)

    ap.assert_called_once_with("/agents/dossier/compile", payload)
    assert out == {"dossier_id": "d-new", "sources": 3}


@pytest.mark.django_db
def test_compile_dossier_with_context_degrades_when_agent_down():
    from apps.common.agent_client import AgentClientError
    from apps.joseph import readers

    with patch("apps.joseph.readers.agent_post", side_effect=AgentClientError("down")):
        assert readers.compile_dossier_with_context({"entity": "X"}) == {}


# ---------------------------------------------------------------------------
# the refresh action — posts the Django thread context, stores dossier_id.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_refresh_dossier_posts_context_and_stores_id(manager, client, thread):
    with patch("apps.crm.thread_views.readers.compile_dossier_with_context") as comp:
        comp.return_value = {"dossier_id": "d-new", "sources": 3}
        resp = client.post(reverse("crm:thread-refresh-dossier", args=[thread.id]))

    assert resp.status_code in (200, 302)
    # context posted = entity/org/contact/track from the Django thread.
    comp.assert_called_once()
    payload = comp.call_args.args[0]
    assert payload["org"] == "Rockefeller Foundation"
    assert payload["entity"] == "Rockefeller Foundation"
    assert payload["contact"] == "Dr. Okonkwo"
    assert payload["track"] == "ai10bn"
    # the returned id is stored on the thread.
    thread.refresh_from_db()
    assert thread.dossier_id == "d-new"


@pytest.mark.django_db
def test_refresh_dossier_agent_down_keeps_thread_unchanged(manager, client, thread):
    with patch("apps.crm.thread_views.readers.compile_dossier_with_context", return_value={}):
        resp = client.post(reverse("crm:thread-refresh-dossier", args=[thread.id]))

    assert resp.status_code in (200, 302)  # never 500
    thread.refresh_from_db()
    assert thread.dossier_id == ""  # unchanged when the seam returns nothing


@pytest.mark.django_db
def test_refresh_dossier_forbidden_for_viewer(viewer, client, thread):
    with patch("apps.crm.thread_views.readers.compile_dossier_with_context") as comp:
        resp = client.post(reverse("crm:thread-refresh-dossier", args=[thread.id]))

    assert resp.status_code == 403
    comp.assert_not_called()
    thread.refresh_from_db()
    assert thread.dossier_id == ""
