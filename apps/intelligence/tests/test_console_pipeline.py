"""Pipeline IA: the content console's pipeline is now the **content** board; the
funder **deal** board moved to CRM (``crm:pipeline``).

- ``/console/pipeline`` → team CONTENT pipeline (created + curated, by stage).
- ``/crm/pipeline/``     → team DEAL pipeline (every owner's threads, drag-restage).

The deal board still reads canonical ``apps.crm.OutreachThread`` rows grouped into
Joseph-parity stage columns with draggable cards (POST to ``crm:thread-set-stage``).
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

DEAL_URL = "/crm/pipeline/"


@pytest.fixture
def staff_client(db):
    """A staff user passes ``_can_manage_crm`` (the CRM gate the deal board uses)."""
    User = get_user_model()
    u = User.objects.create_user(
        email="op3@x.io", password="pw", name="Op3",
        tos_accepted_at=timezone.now(), is_staff=True,
    )
    c = Client()
    c.force_login(u)
    return c


@pytest.fixture
def member_client(db, organization, workspace):
    """An ordinary workspace member — must be 403'd from the CRM deal pipeline."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    u = User.objects.create_user(
        email="member-pipeline@x.io", password="pw", name="Member",
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
    c = Client()
    c.force_login(u)
    return c


@pytest.fixture
def crm_thread(db):
    """A CRM org + contact + outreach thread (stage=proposal_sent)."""
    from apps.crm.models import Contact, Organization, OutreachThread

    org = Organization.objects.create(name="AfDB")
    contact = Contact.objects.create(org=org, full_name="Dr. Adesina")
    return OutreachThread.objects.create(
        org=org, primary_contact=contact,
        stage=OutreachThread.Stage.PROPOSAL,
        track="ai10bn", traffic_light="amber", quintile=4,
        next_action="Send revised term sheet",
    )


# ── Deal board (relocated to CRM) ───────────────────────────────────────────

@pytest.mark.django_db
def test_deal_pipeline_renders_crm_threads_grouped_by_stage(staff_client, crm_thread):
    resp = staff_client.get(DEAL_URL)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Deal pipeline" in body  # relabeled, no longer "Team pipeline"
    assert "AfDB" in body
    assert "Proposal" in body and "Discover" in body and "Committed" in body


@pytest.mark.django_db
def test_deal_pipeline_wires_drag_drop_to_set_stage(staff_client, crm_thread):
    resp = staff_client.get(DEAL_URL)
    body = resp.content.decode()
    assert "cdn.jsdelivr.net" in body and "Sortable" in body
    assert "/crm/threads/" in body and "/stage/" in body
    assert f'data-thread-id="{crm_thread.id}"' in body
    assert 'data-stage="proposal"' in body


@pytest.mark.django_db
def test_deal_pipeline_init_script_is_nonced(staff_client, crm_thread):
    resp = staff_client.get(DEAL_URL)
    body = resp.content.decode()
    assert 'nonce="' in body
    assert "onclick=" not in body and "onsubmit=" not in body


@pytest.mark.django_db
def test_deal_pipeline_forbidden_for_non_crm_role(member_client, crm_thread):
    resp = member_client.get(DEAL_URL)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_deal_pipeline_empty_db_renders_columns(staff_client):
    resp = staff_client.get(DEAL_URL)
    assert resp.status_code == 200
    assert "Discover" in resp.content.decode()


@pytest.fixture
def owned_threads(db):
    """Two CRM threads owned by two users across two tracks — for the Owner
    badge + owner/track filter chips on the deal board."""
    from apps.accounts.models import User
    from apps.crm.models import Organization, OutreachThread

    alice = User.objects.create_user(
        email="alice-pl@x.io", password="pw", name="Alice Owner", tos_accepted_at=timezone.now())
    bob = User.objects.create_user(
        email="bob-pl@x.io", password="pw", name="Bob Owner", tos_accepted_at=timezone.now())
    org_a = Organization.objects.create(name="GreenClimate")
    org_b = Organization.objects.create(name="WorldBank")
    ta = OutreachThread.objects.create(
        org=org_a, owner=alice, stage=OutreachThread.Stage.ENGAGED,
        track="ai10bn", traffic_light="green", quintile=5)
    tb = OutreachThread.objects.create(
        org=org_b, owner=bob, stage=OutreachThread.Stage.PROPOSAL,
        track="energy", traffic_light="amber", quintile=3)
    return {"alice": alice, "bob": bob, "ta": ta, "tb": tb}


@pytest.mark.django_db
def test_deal_pipeline_shows_owner_badges(staff_client, owned_threads):
    resp = staff_client.get(DEAL_URL)
    body = resp.content.decode()
    assert "Deal pipeline" in body and "My pipeline" not in body
    assert "Alice Owner" in body and "Bob Owner" in body


@pytest.mark.django_db
def test_deal_pipeline_owner_filter_narrows(staff_client, owned_threads):
    alice = owned_threads["alice"]
    resp = staff_client.get(DEAL_URL)
    body = resp.content.decode()
    assert f"owner={alice.id}" in body
    resp = staff_client.get(f"{DEAL_URL}?owner={alice.id}")
    body = resp.content.decode()
    assert "GreenClimate" in body and "WorldBank" not in body


@pytest.mark.django_db
def test_deal_pipeline_track_filter_narrows(staff_client, owned_threads):
    resp = staff_client.get(f"{DEAL_URL}?track=energy")
    body = resp.content.decode()
    assert "WorldBank" in body and "GreenClimate" not in body


# ── Content board (the repurposed console pipeline) ─────────────────────────

@pytest.fixture
def content_member(db, organization, workspace):
    """A logged-in workspace member (the content pipeline is content-ops, not gated
    to CRM roles)."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    u = User.objects.create_user(
        email="content@x.io", password="pw", name="Content Op", tos_accepted_at=timezone.now())
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    c = Client()
    c.force_login(u)
    return c


@pytest.mark.django_db
def test_console_pipeline_is_the_content_board(content_member, workspace):
    """/console/pipeline is now the CONTENT board: stage columns fed by created +
    curated content — not deal threads."""
    from apps.composer.models import Post
    from apps.content_intake.models import ContentIntake
    Post.objects.create(workspace=workspace, caption="A created draft", title="Created One")
    ContentIntake.objects.create(workspace=workspace, external_id="cur-1",
        sensitivity="public_safe", status=ContentIntake.Status.PUBLISHED, angle="Curated One")

    resp = content_member.get("/console/pipeline")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Content pipeline" in body
    assert "Created One" in body and "Curated One" in body
    # stage column labels present; it is NOT the deal board
    assert "Published" in body
    assert "Deal pipeline" not in body


@pytest.mark.django_db
def test_console_pipeline_no_agent_call(content_member, monkeypatch):
    """The content board reads Django only — no agent-service call."""
    from apps.intelligence import console_views
    calls = []
    monkeypatch.setattr(console_views, "safe_get", lambda *a, **k: calls.append(a) or {"items": []})
    resp = content_member.get("/console/pipeline")
    assert resp.status_code == 200
    assert calls == []


@pytest.mark.django_db
def test_notification_read_posts(staff_client, monkeypatch):
    from apps.intelligence import console_views
    calls = {}
    monkeypatch.setattr(console_views, "agent_post",
                        lambda path, json=None: calls.setdefault("path", path) or {})
    resp = staff_client.post("/console/notifications/n1/read")
    assert resp.status_code in (302, 303) and calls["path"] == "/notifications/n1/read"
