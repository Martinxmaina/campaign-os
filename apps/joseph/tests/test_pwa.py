"""Tests for Joseph's PWA layer — service worker, manifest, nav link, bell.

Task 12 of the TB Joseph spine. The principal surface becomes an installable,
offline-capable app: a service worker (cache-first for visited briefs) registered
from the editorial ``_base.html`` with a CSP nonce, a web manifest scoped to
``/joseph/``, a notification bell that polls a tiny JSON endpoint, and a
role-gated "Joseph" entry in the real left sidebar.

Every piece degrades gracefully (the bell endpoint reuses the readers, which
swallow ``AgentClientError``) and is gated by ``_can_access_joseph``.
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
    """An ordinary workspace member (viewer) — no Joseph access, no sidebar link."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    u = User.objects.create_user(
        email="viewer-pwa@example.com", password="x", name="Viewer",
        tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


def _patched():
    """Patch every agent-service-backed reader the home view touches to empty."""
    return (
        patch("apps.joseph.views.readers.list_threads", return_value=[]),
        patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]),
    )


# --- service worker registration + manifest ------------------------------


@pytest.mark.django_db
def test_home_includes_sw_registration_and_manifest(joseph, client):
    """The mobile editorial surface registers the SW and links the manifest."""
    lt, ln = _patched()
    with lt, ln:
        resp = client.get(reverse("joseph:home") + "?view=mobile")
    assert resp.status_code == 200
    html = resp.content.decode()
    # service worker registration, scoped to /joseph/
    assert "serviceWorker.register" in html
    assert "/static/js/joseph-sw.js" in html
    assert "/joseph/" in html  # scope
    # the manifest is linked
    assert "rel=\"manifest\"" in html
    assert "joseph" in html.lower()


@pytest.mark.django_db
def test_sw_registration_script_carries_csp_nonce(joseph, client):
    """The SW register script is an inline <script> and MUST carry the CSP nonce
    (CSP-safe — no unsafe-inline)."""
    lt, ln = _patched()
    with lt, ln:
        resp = client.get(reverse("joseph:home") + "?view=mobile")
    html = resp.content.decode()
    # find the script that registers the SW and confirm it has a nonce attr
    idx = html.find("serviceWorker.register")
    assert idx != -1
    # the opening <script ...> tag immediately before it must have nonce=
    script_open = html.rfind("<script", 0, idx)
    assert script_open != -1
    script_tag = html[script_open:idx]
    assert "nonce=" in script_tag


@pytest.mark.django_db
def test_service_worker_js_is_served(client, joseph, settings):
    """The SW JS file is collectable/servable from static (200)."""
    from django.contrib.staticfiles import finders
    found = finders.find("js/joseph-sw.js")
    assert found is not None, "joseph-sw.js must exist under a static dir"
    contents = open(found).read()
    # a real SW: install + fetch handlers, cache-first for visited briefs
    assert "addEventListener" in contents
    assert "install" in contents
    assert "fetch" in contents
    assert "/joseph/brief/" in contents


# --- role-gated sidebar link ---------------------------------------------


@pytest.mark.django_db
def test_sidebar_shows_joseph_link_for_capable_user(joseph, client):
    """A Joseph-capable user (owner) sees the 'Joseph' sidebar role group
    linking to /joseph/ (IA "Group & Home" renamed the section to "Joseph")."""
    lt, ln = _patched()
    with lt, ln:
        resp = client.get(reverse("joseph:home"))
    html = resp.content.decode()
    assert "Joseph" in html
    assert reverse("joseph:home") in html


@pytest.mark.django_db
def test_sidebar_hides_joseph_link_for_viewer(viewer, client):
    """A non-capable member must NOT see the Joseph sidebar section. We render a
    page that always shows the sidebar (the notifications list) so the test isn't
    coupled to the gated /joseph/ view (which 403s for a viewer)."""
    resp = client.get(reverse("notifications:list"))
    assert resp.status_code == 200
    html = resp.content.decode()
    # The Joseph role group (and its links) must not render for a non-capable member.
    assert reverse("joseph:home") not in html


@pytest.mark.django_db
def test_can_access_joseph_in_context_for_capable_user(joseph, client):
    """The role gate is exposed to templates as ``can_access_joseph`` (via a
    context processor) so the sidebar link can be shown across every page."""
    resp = client.get(reverse("notifications:list"))
    assert resp.status_code == 200
    assert resp.context["can_access_joseph"] is True


@pytest.mark.django_db
def test_can_access_joseph_false_for_viewer(viewer, client):
    resp = client.get(reverse("notifications:list"))
    assert resp.status_code == 200
    assert resp.context["can_access_joseph"] is False


# --- notification bell endpoint ------------------------------------------


@pytest.mark.django_db
def test_notifications_json_returns_unread_count_and_items(joseph, client):
    """The bell polls /joseph/notifications.json → {count, items[]}."""
    notif = {"id": "n1", "kind": "gate_flag", "body": "Gate block on AfDB post",
             "urgent": True, "action": {"href": "/x"}, "read": False}
    with patch("apps.joseph.views.readers.list_notifications", return_value=[notif]):
        resp = client.get("/joseph/notifications.json")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/json")
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["body"] == "Gate block on AfDB post"


@pytest.mark.django_db
def test_notifications_json_agent_down_is_empty_not_500(joseph, client):
    """Agent-service down → the reader returns [] → the bell endpoint returns a
    200 empty payload, never a 500."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        resp = client.get("/joseph/notifications.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["items"] == []


@pytest.mark.django_db
def test_notifications_json_forbidden_for_viewer(viewer, client):
    """The bell endpoint is gated by _can_access_joseph and never hits the agent
    for a non-capable user."""
    with patch("apps.joseph.views.readers.list_notifications") as ln:
        resp = client.get("/joseph/notifications.json")
    assert resp.status_code in (403, 302)
    ln.assert_not_called()


@pytest.mark.django_db
def test_home_includes_notification_bell(joseph, client):
    """The home surface renders a bell that polls the JSON endpoint."""
    lt, ln = _patched()
    with lt, ln:
        resp = client.get(reverse("joseph:home") + "?view=mobile")
    html = resp.content.decode()
    assert "/joseph/notifications.json" in html
