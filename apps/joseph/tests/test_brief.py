"""Tests for Joseph's dossier brief card at /joseph/brief/<thread_id>/.

The L0 card maps a thread+dossier onto the editorial six fields (WHO / WHY NOW /
HOOK / RED FLAGS / WARM PATH / FRESHNESS); ?tier=l1|l2 swaps to the dossier body
(HTMX partial); POST .../refresh/ triggers a dossier compile. The view is gated
by ``_can_access_joseph`` and degrades gracefully when the agent-service is down
(empty state / "Compile" CTA, never a 500).
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


THREAD = {
    "id": "t1",
    "org": "Rockefeller Foundation",
    "track": "climate",
    "stage": "qualify",
    "dossier_id": "d1",
    "state": {"contact_name": "Dr. Rajiv Shah", "contact_role": "President"},
}
DOSSIER = {
    "id": "d1",
    "entity": "Rockefeller Foundation",
    "summary": "Closing a $500M Africa climate window this quarter.",
    "body_md": "## Overview\nLong-form dossier body.",
    "sources": [{"ref": "s1", "trust": 0.9}, {"ref": "s2", "trust": 0.8}],
    "red_flags": ["Slow legal", "Board reshuffle", "FX exposure"],
    "hooks": {"climate": "Lead with the SE4ALL precedent."},
    "meta": {"warm_path": "Intro via Dr. Shah's chief of staff."},
    "updated_at": "2026-06-14T10:00:00Z",
    "status": "ready",
    "thread_id": "t1",
}


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
    """An ordinary workspace member (viewer) — must not reach the brief."""
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


def _patch_readers(thread=THREAD, dossier=DOSSIER):
    return (
        patch("apps.joseph.intelligence.readers.get_thread", return_value=thread),
        patch("apps.joseph.intelligence.readers.get_dossier", return_value=dossier),
    )


# --------------------------------------------------------------------------
# L0 card
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_brief_l0_renders_six_editorial_fields(joseph, client):
    pt, pd = _patch_readers()
    with pt, pd:
        resp = client.get(reverse("joseph:brief", args=["t1"]))
    assert resp.status_code == 200
    body = resp.content
    # the six L0 labels
    assert b"WHO" in body
    assert b"WHY NOW" in body
    assert b"HOOK" in body
    assert b"RED FLAGS" in body
    assert b"WARM PATH" in body
    assert b"FRESHNESS" in body
    # the mapped content
    assert b"Rockefeller Foundation" in body
    assert b"Dr. Rajiv Shah" in body
    assert b"Closing a $500M Africa climate window this quarter." in body
    assert b"Lead with the SE4ALL precedent." in body
    assert b"Slow legal" in body
    assert b"Intro via Dr. Shah" in body


@pytest.mark.django_db
def test_brief_forbidden_for_viewer(viewer, client):
    """A non-owner/admin/principal member must not reach the brief; the
    agent-service must not be hit at all."""
    with patch("apps.joseph.intelligence.readers.get_thread") as gt:
        resp = client.get(reverse("joseph:brief", args=["t1"]))
    assert resp.status_code in (403, 302)
    gt.assert_not_called()


@pytest.mark.django_db
def test_brief_agent_down_renders_compile_cta_no_500(joseph, client):
    """Agent-service down → readers swallow AgentClientError and return safe
    defaults → no dossier → a 200 page with a Compile CTA, never a 500."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        resp = client.get(reverse("joseph:brief", args=["t1"]))
    assert resp.status_code == 200
    assert b"Compile" in resp.content


@pytest.mark.django_db
def test_brief_no_dossier_shows_compile_cta(joseph, client):
    """A thread with no dossier_id → 'No dossier yet — Compile' CTA."""
    thread = {"id": "t1", "org": "X"}  # no dossier_id
    with patch("apps.joseph.intelligence.readers.get_thread", return_value=thread), \
         patch("apps.joseph.intelligence.readers.get_dossier", return_value={}):
        resp = client.get(reverse("joseph:brief", args=["t1"]))
    assert resp.status_code == 200
    assert b"No dossier yet" in resp.content
    assert b"Compile" in resp.content


# --------------------------------------------------------------------------
# tier toggle (L1 / L2 HTMX partials)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_brief_l1_returns_body_md_partial(joseph, client):
    pt, pd = _patch_readers()
    with pt, pd:
        resp = client.get(reverse("joseph:brief", args=["t1"]) + "?tier=l1",
                           HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert b"Long-form dossier body." in resp.content
    # HTMX partial must NOT re-render the whole page chrome
    assert b"<html" not in resp.content.lower()


@pytest.mark.django_db
def test_brief_l2_returns_wiki_or_body_partial(joseph, client):
    pt, pd = _patch_readers()
    page = {"slug": "rockefeller-foundation", "tier": "l2", "content": "WIKI L2 BODY"}
    with pt, pd, patch("apps.joseph.intelligence.readers.get_page", return_value=page):
        resp = client.get(reverse("joseph:brief", args=["t1"]) + "?tier=l2",
                           HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert b"WIKI L2 BODY" in resp.content


@pytest.mark.django_db
def test_brief_tier_buttons_use_hx_get(joseph, client):
    """The L0/L1/L2 toggle is CSP-safe: hx-get + hx-target, no inline onclick."""
    pt, pd = _patch_readers()
    with pt, pd:
        resp = client.get(reverse("joseph:brief", args=["t1"]))
    body = resp.content
    assert b"hx-get" in body
    assert b"onclick=" not in body
    assert b"onsubmit=" not in body


# --------------------------------------------------------------------------
# refresh (POST → dossier compile)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_brief_refresh_posts_compile_and_redirects(joseph, client):
    with patch("apps.joseph.views.readers.compile_dossier", return_value={"dossier_id": "d2"}) as comp:
        resp = client.post(reverse("joseph:brief-refresh", args=["t1"]))
    comp.assert_called_once_with("t1")
    assert resp.status_code in (302, 303)
    assert "/joseph/brief/t1/" in resp["Location"]


@pytest.mark.django_db
def test_brief_refresh_forbidden_for_viewer(viewer, client):
    with patch("apps.joseph.views.readers.compile_dossier") as comp:
        resp = client.post(reverse("joseph:brief-refresh", args=["t1"]))
    assert resp.status_code in (403, 302)
    comp.assert_not_called()
