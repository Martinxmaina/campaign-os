"""Tests for the CRM Organizations + Contacts CRUD surface (Task 7).

These are pure-Django views — the canonical CRM lives in Django, so NO call to
agent-service is made (the Joseph pipeline still hits agent-service; this CRM
surface does not). Each view is gated by ``_can_manage_crm`` (staff or an
owner/admin/campaign_owner workspace role), CSP-safe (no inline handlers — Alpine
``@click`` + ``hx-*`` only), and extends ``base.html`` (BrightBean skin).

Surface under test:
  /crm/orgs/                 → list (filter ?tier / ?type, search ?q)
  /crm/orgs/new/             → create form  (POST → new Organization)
  /crm/orgs/<id>/            → detail (its contacts + threads)
  /crm/orgs/<id>/edit/       → edit form    (POST → updated Organization)
  /crm/contacts/             → list (filter ?org / ?seniority, search ?q)
  /crm/contacts/new/         → create form  (POST → new Contact)
  /crm/contacts/<id>/        → detail (its threads)
  /crm/contacts/<id>/edit/   → edit form    (POST → updated Contact)
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


# ---------------------------------------------------------------------------
# Role fixtures (mirror test_import_views.py) — manager passes, viewer 403s.
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
    """An ordinary member (viewer) — must be 403'd from the CRUD surface."""
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
def seed_orgs(db):
    """A couple of orgs (different tier/type) + a contact + a thread."""
    from apps.crm.models import Contact, Organization, OutreachThread

    rockefeller = Organization.objects.create(
        name="Rockefeller Foundation",
        type=Organization.Type.FUNDER,
        tier=Organization.Tier.T1,
        track_tags=["ai10bn"],
    )
    geapp = Organization.objects.create(
        name="GEAPP",
        type=Organization.Type.DFI,
        tier=Organization.Tier.T2,
    )
    okonkwo = Contact.objects.create(
        org=rockefeller, full_name="Dr. Okonkwo",
        seniority=Contact.Seniority.VP, email="okonkwo@rockefeller.org",
    )
    OutreachThread.objects.create(
        org=rockefeller, primary_contact=okonkwo, stage=OutreachThread.Stage.ENGAGED,
        track="ai10bn",
    )
    return {"rockefeller": rockefeller, "geapp": geapp, "okonkwo": okonkwo}


# ---------------------------------------------------------------------------
# Organizations — list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_org_list_renders_for_manager(manager, client, seed_orgs):
    resp = client.get(reverse("crm:org-list"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Rockefeller Foundation" in body
    assert "GEAPP" in body
    # CSP-safe — no inline event handlers in the rendered HTML.
    assert "onclick=" not in body
    assert "onsubmit=" not in body


@pytest.mark.django_db
def test_org_list_forbidden_for_viewer(viewer, client):
    resp = client.get(reverse("crm:org-list"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_org_list_filters_by_tier(manager, client, seed_orgs):
    resp = client.get(reverse("crm:org-list"), {"tier": "tier1_anchor"})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Rockefeller Foundation" in body
    assert "GEAPP" not in body


@pytest.mark.django_db
def test_org_list_filters_by_type(manager, client, seed_orgs):
    resp = client.get(reverse("crm:org-list"), {"type": "dfi"})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "GEAPP" in body
    assert "Rockefeller Foundation" not in body


@pytest.mark.django_db
def test_org_list_search_by_name(manager, client, seed_orgs):
    resp = client.get(reverse("crm:org-list"), {"q": "rockefeller"})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Rockefeller Foundation" in body
    assert "GEAPP" not in body


@pytest.mark.django_db
def test_org_list_does_not_call_agent_service(manager, client, seed_orgs):
    # Pure Django — agent_get must never be touched by this surface.
    with patch("apps.common.agent_client.agent_get") as ag:
        resp = client.get(reverse("crm:org-list"))
    assert resp.status_code == 200
    ag.assert_not_called()


# ---------------------------------------------------------------------------
# Organizations — create / detail / edit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_org_new_form_renders(manager, client):
    resp = client.get(reverse("crm:org-new"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_org_new_forbidden_for_viewer(viewer, client):
    resp = client.get(reverse("crm:org-new"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_org_create_persists(manager, client):
    from apps.crm.models import Organization

    resp = client.post(
        reverse("crm:org-new"),
        {"name": "Mastercard Foundation", "type": "funder", "tier": "tier1_anchor"},
    )
    assert resp.status_code in (302, 200)
    org = Organization.objects.get(name="Mastercard Foundation")
    assert org.type == "funder"
    assert org.tier == "tier1_anchor"


@pytest.mark.django_db
def test_org_create_forbidden_for_viewer(viewer, client):
    from apps.crm.models import Organization

    resp = client.post(reverse("crm:org-new"), {"name": "Should Not Exist"})
    assert resp.status_code == 403
    assert not Organization.objects.filter(name="Should Not Exist").exists()


@pytest.mark.django_db
def test_org_detail_shows_contacts_and_threads(manager, client, seed_orgs):
    org = seed_orgs["rockefeller"]
    resp = client.get(reverse("crm:org-detail", args=[org.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Dr. Okonkwo" in body          # its contact
    assert "engaged" in body.lower()       # its thread's stage


@pytest.mark.django_db
def test_org_detail_forbidden_for_viewer(viewer, client, seed_orgs):
    org = seed_orgs["rockefeller"]
    resp = client.get(reverse("crm:org-detail", args=[org.id]))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_org_edit_updates(manager, client, seed_orgs):
    org = seed_orgs["geapp"]
    resp = client.post(
        reverse("crm:org-edit", args=[org.id]),
        {"name": "GEAPP", "type": "dfi", "tier": "tier1_anchor", "notes": "moved up"},
    )
    assert resp.status_code in (302, 200)
    org.refresh_from_db()
    assert org.tier == "tier1_anchor"
    assert org.notes == "moved up"


# ---------------------------------------------------------------------------
# Contacts — list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_contact_list_renders_for_manager(manager, client, seed_orgs):
    resp = client.get(reverse("crm:contact-list"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Dr. Okonkwo" in body


@pytest.mark.django_db
def test_contact_list_forbidden_for_viewer(viewer, client):
    resp = client.get(reverse("crm:contact-list"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_contact_list_search_by_name(manager, client, seed_orgs):
    from apps.crm.models import Contact

    Contact.objects.create(org=seed_orgs["geapp"], full_name="Jane Doe")
    resp = client.get(reverse("crm:contact-list"), {"q": "okonkwo"})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Dr. Okonkwo" in body
    assert "Jane Doe" not in body


@pytest.mark.django_db
def test_contact_list_filters_by_org(manager, client, seed_orgs):
    from apps.crm.models import Contact

    Contact.objects.create(org=seed_orgs["geapp"], full_name="Jane Doe")
    resp = client.get(reverse("crm:contact-list"), {"org": str(seed_orgs["geapp"].id)})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Jane Doe" in body
    assert "Dr. Okonkwo" not in body


@pytest.mark.django_db
def test_contact_list_filters_by_seniority(manager, client, seed_orgs):
    from apps.crm.models import Contact

    Contact.objects.create(
        org=seed_orgs["geapp"], full_name="Jane Doe",
        seniority=Contact.Seniority.AN,
    )
    resp = client.get(reverse("crm:contact-list"), {"seniority": "vp"})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Dr. Okonkwo" in body  # the VP
    assert "Jane Doe" not in body


# ---------------------------------------------------------------------------
# Contacts — create / detail / edit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_contact_new_form_renders(manager, client, seed_orgs):
    resp = client.get(reverse("crm:contact-new"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_contact_create_persists(manager, client, seed_orgs):
    from apps.crm.models import Contact

    resp = client.post(
        reverse("crm:contact-new"),
        {
            "org": str(seed_orgs["geapp"].id),
            "full_name": "Sam Mwangi",
            "email": "sam@geapp.org",
            "seniority": "director",
        },
    )
    assert resp.status_code in (302, 200)
    c = Contact.objects.get(full_name="Sam Mwangi")
    assert c.org_id == seed_orgs["geapp"].id
    assert c.email == "sam@geapp.org"


@pytest.mark.django_db
def test_contact_create_forbidden_for_viewer(viewer, client, seed_orgs):
    from apps.crm.models import Contact

    resp = client.post(
        reverse("crm:contact-new"),
        {"org": str(seed_orgs["geapp"].id), "full_name": "Nope"},
    )
    assert resp.status_code == 403
    assert not Contact.objects.filter(full_name="Nope").exists()


@pytest.mark.django_db
def test_contact_detail_shows_threads(manager, client, seed_orgs):
    c = seed_orgs["okonkwo"]
    resp = client.get(reverse("crm:contact-detail", args=[c.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Dr. Okonkwo" in body
    assert "Rockefeller Foundation" in body  # its org / its thread's org


@pytest.mark.django_db
def test_contact_edit_updates(manager, client, seed_orgs):
    c = seed_orgs["okonkwo"]
    resp = client.post(
        reverse("crm:contact-edit", args=[c.id]),
        {
            "org": str(c.org_id),
            "full_name": "Dr. Adaeze Okonkwo",
            "email": "okonkwo@rockefeller.org",
            "seniority": "c_suite",
        },
    )
    assert resp.status_code in (302, 200)
    c.refresh_from_db()
    assert c.full_name == "Dr. Adaeze Okonkwo"
    assert c.seniority == "c_suite"
