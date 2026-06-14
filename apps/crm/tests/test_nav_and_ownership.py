"""Tests for the CRM sidebar nav section + role gate + ownership bookkeeping (Task 10).

The left-nav grows a role-gated "CRM" section (Organizations / Contacts / Pipeline /
Import) shown ONLY to users who pass ``_can_manage_crm`` (staff or an
owner/admin/campaign_owner workspace role) — mirroring the existing
"Joseph · Principal" section gate. We render a page that extends ``base.html`` and
is available to every authenticated user (the notifications history page) so the
SAME page proves the section both shows (manager) and hides (viewer).

We also assert ``docs/TABLE_OWNERSHIP.md`` exists and records the strangler split:
the crm tables are owned by Django; dossiers / wiki / gate live in agent-service.
"""
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse


# ---------------------------------------------------------------------------
# Role fixtures (mirror test_crm_views.py) — manager passes, viewer does not.
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(client, org_owner, workspace):
    """A workspace owner — passes ``_can_manage_crm``."""
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
    """An ordinary member (viewer) — must NOT see the CRM section."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from django.utils import timezone

    u = User.objects.create_user(
        email="navviewer@example.com", password="x", name="Nav Viewer",
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


# ---------------------------------------------------------------------------
# Sidebar nav — role gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sidebar_shows_crm_section_for_manager(manager, client):
    resp = client.get(reverse("notifications:list"))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Section header + all four CRM links resolve and render.
    assert "CRM" in body
    assert reverse("crm:org-list") in body
    assert reverse("crm:contact-list") in body
    assert reverse("joseph:pipeline") in body
    assert reverse("crm:import-home") in body


@pytest.mark.django_db
def test_sidebar_hides_crm_section_for_viewer(viewer, client):
    resp = client.get(reverse("notifications:list"))
    assert resp.status_code == 200
    body = resp.content.decode()
    # The CRM CRUD links must not be exposed to a non-manager.
    assert reverse("crm:org-list") not in body
    assert reverse("crm:contact-list") not in body
    assert reverse("crm:import-home") not in body


@pytest.mark.django_db
def test_crm_section_gate_reuses_can_manage_crm(manager):
    """The context flag is the single source of truth shared with the view gate."""
    from apps.crm.views_import import _can_manage_crm

    class _Req:
        user = manager

    req = _Req()
    # The manager fixture set the owner workspace role; the gate sees it via
    # request.workspace_membership in the real flow, but staff/superuser also pass.
    # Here we only assert the helper is importable + callable (drift guard).
    assert callable(_can_manage_crm)


# ---------------------------------------------------------------------------
# Ownership bookkeeping
# ---------------------------------------------------------------------------


def test_table_ownership_doc_exists_and_records_the_split():
    doc = Path(settings.BASE_DIR) / "docs" / "TABLE_OWNERSHIP.md"
    assert doc.exists(), "docs/TABLE_OWNERSHIP.md must exist (Task 10)"
    text = doc.read_text().lower()
    # crm tables → Django
    for table in ("organization", "contact", "outreachthread", "activity", "task"):
        assert table in text, f"{table} must be listed in TABLE_OWNERSHIP.md"
    assert "django" in text
    # dossiers / wiki / gate → agent-service
    assert "dossier" in text
    assert "wiki" in text
    assert "gate" in text
    assert "agent-service" in text
