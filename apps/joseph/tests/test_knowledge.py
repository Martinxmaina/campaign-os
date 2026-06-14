"""Tests for Joseph's knowledge browser at /joseph/knowledge/ + detail.

The browser searches the agent-service wiki (``/knowledge/pages?q&entity_type``)
with entity_type filter chips (funder/org/person/initiative/topic). The detail
page (``/joseph/knowledge/<slug>/``) shows the page title + L1 overview with an
L0/L1/L2 tier toggle (HTMX swap), lists revisions, and renders outgoing links as
in-app links. Both views are gated by ``_can_access_joseph`` and degrade
gracefully when the agent-service is down (empty states, never a 500). CSP-safe:
HTMX tier toggle + plain anchors, no inline onclick/onsubmit.
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


PAGES = [
    {"slug": "rockefeller-foundation", "title": "Rockefeller Foundation",
     "entity_type": "funder", "status": "verified"},
    {"slug": "rockefeller-climate-facility", "title": "Rockefeller — climate facility",
     "entity_type": "initiative", "status": "unverified"},
]
PAGE = {
    "slug": "rockefeller-foundation",
    "title": "Rockefeller Foundation",
    "tier": "l1",
    "status": "verified",
    "aliases": ["RF", "Rockefeller"],
    "links": ["GEAPP", "SE4ALL", "catalytic-capital"],
    "content": "A US philanthropy with a long catalytic-capital track record.",
}
PAGE_L2 = {
    "slug": "rockefeller-foundation",
    "title": "Rockefeller Foundation",
    "tier": "l2",
    "status": "verified",
    "aliases": [],
    "links": [],
    "content": "L2 FULL BODY — the long-form wiki page.",
}
REVISIONS = [
    {"diff": "+ added 2026 climate facility", "source_refs": ["s1"],
     "created_at": "2026-06-13T10:00:00Z"},
    {"diff": "+ initial page", "source_refs": ["s0"], "created_at": "2026-06-01T09:00:00Z"},
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
    """An ordinary workspace member (viewer) — must not reach the knowledge browser."""
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
# browser /joseph/knowledge/
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_knowledge_lists_pages(joseph, client):
    """GET /joseph/knowledge/?q=rock&entity_type=funder → 200, lists pages."""
    with patch("apps.joseph.views.readers.search_pages", return_value=PAGES) as sp:
        resp = client.get(reverse("joseph:knowledge") + "?q=rock&entity_type=funder")
    assert resp.status_code == 200
    body = resp.content
    assert b"Rockefeller Foundation" in body
    assert b"Rockefeller \xe2\x80\x94 climate facility" in body  # em-dash, utf-8
    # the search reader is called with the q + entity_type filter
    sp.assert_called_once()
    kwargs = sp.call_args.kwargs
    args = sp.call_args.args
    assert "rock" in (list(kwargs.values()) + list(args))
    assert "funder" in (list(kwargs.values()) + list(args))


@pytest.mark.django_db
def test_knowledge_renders_entity_type_filter_chips(joseph, client):
    """The browser shows entity_type filter chips."""
    with patch("apps.joseph.views.readers.search_pages", return_value=[]):
        resp = client.get(reverse("joseph:knowledge"))
    body = resp.content
    for chip in (b"funder", b"org", b"person", b"initiative", b"topic"):
        assert chip in body


@pytest.mark.django_db
def test_knowledge_card_links_to_detail(joseph, client):
    """Each result card links into the page detail."""
    with patch("apps.joseph.views.readers.search_pages", return_value=PAGES):
        resp = client.get(reverse("joseph:knowledge"))
    assert b"/joseph/knowledge/rockefeller-foundation/" in resp.content


@pytest.mark.django_db
def test_knowledge_forbidden_for_viewer(viewer, client):
    """A non-owner/admin/principal member must not reach the browser; the
    agent-service must not be hit at all."""
    with patch("apps.joseph.views.readers.search_pages") as sp:
        resp = client.get(reverse("joseph:knowledge"))
    assert resp.status_code in (403, 302)
    sp.assert_not_called()


@pytest.mark.django_db
def test_knowledge_agent_down_renders_no_500(joseph, client):
    """Agent-service down → search_pages swallows AgentClientError → [] → a 200
    page with an empty state, never a 500."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        resp = client.get(reverse("joseph:knowledge") + "?q=x")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_knowledge_csp_safe_no_inline_handlers(joseph, client):
    """The browser is CSP-safe — no inline onclick/onsubmit handlers."""
    with patch("apps.joseph.views.readers.search_pages", return_value=PAGES):
        resp = client.get(reverse("joseph:knowledge"))
    assert b"onclick=" not in resp.content
    assert b"onsubmit=" not in resp.content


# --------------------------------------------------------------------------
# detail /joseph/knowledge/<slug>/
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_knowledge_detail_shows_title_and_l1(joseph, client):
    """GET /joseph/knowledge/<slug>/ → 200 shows title + L1 content + revisions."""
    with patch("apps.joseph.views.readers.get_page", return_value=PAGE) as gp, \
         patch("apps.joseph.views.readers.page_revisions", return_value=REVISIONS):
        resp = client.get(reverse("joseph:knowledge-detail", args=["rockefeller-foundation"]))
    assert resp.status_code == 200
    body = resp.content
    assert b"Rockefeller Foundation" in body
    assert b"long catalytic-capital track record" in body
    # the page is fetched at the L1 tier by default
    gp.assert_called_once()
    assert "l1" in str(gp.call_args)
    # revisions are listed
    assert b"added 2026 climate facility" in body


@pytest.mark.django_db
def test_knowledge_detail_renders_links_as_in_app_links(joseph, client):
    """Outgoing wiki links render as in-app links to other knowledge pages."""
    with patch("apps.joseph.views.readers.get_page", return_value=PAGE), \
         patch("apps.joseph.views.readers.page_revisions", return_value=[]):
        resp = client.get(reverse("joseph:knowledge-detail", args=["rockefeller-foundation"]))
    body = resp.content
    assert b"GEAPP" in body
    # the link target is an in-app knowledge URL (slugified)
    assert b"/joseph/knowledge/geapp/" in body


@pytest.mark.django_db
def test_knowledge_detail_tier_toggle_swaps_body(joseph, client):
    """?tier=l2 fetches the L2 body and (HTMX) returns just the body partial."""
    with patch("apps.joseph.views.readers.get_page", return_value=PAGE_L2) as gp, \
         patch("apps.joseph.views.readers.page_revisions", return_value=[]):
        resp = client.get(
            reverse("joseph:knowledge-detail", args=["rockefeller-foundation"]) + "?tier=l2",
            HTTP_HX_REQUEST="true",
        )
    assert resp.status_code == 200
    body = resp.content
    assert b"L2 FULL BODY" in body
    # the page is fetched at the requested tier
    assert "l2" in str(gp.call_args)
    # HTMX partial must NOT re-render the whole page chrome
    assert b"<html" not in body.lower()


@pytest.mark.django_db
def test_knowledge_detail_forbidden_for_viewer(viewer, client):
    """A viewer must not reach a page detail; the agent-service must not be hit."""
    with patch("apps.joseph.views.readers.get_page") as gp:
        resp = client.get(reverse("joseph:knowledge-detail", args=["rockefeller-foundation"]))
    assert resp.status_code in (403, 302)
    gp.assert_not_called()


@pytest.mark.django_db
def test_knowledge_detail_agent_down_renders_no_500(joseph, client):
    """Agent-service down → readers return safe defaults → a 200 page with an
    empty state, never a 500."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        resp = client.get(reverse("joseph:knowledge-detail", args=["rockefeller-foundation"]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_knowledge_detail_csp_safe_no_inline_handlers(joseph, client):
    """The detail page is CSP-safe — HTMX tier toggle, no inline handlers."""
    with patch("apps.joseph.views.readers.get_page", return_value=PAGE), \
         patch("apps.joseph.views.readers.page_revisions", return_value=REVISIONS):
        resp = client.get(reverse("joseph:knowledge-detail", args=["rockefeller-foundation"]))
    body = resp.content
    assert b"hx-get" in body
    assert b"onclick=" not in body
    assert b"onsubmit=" not in body
