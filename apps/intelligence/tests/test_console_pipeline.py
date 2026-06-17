"""Console pipeline reads canonical Django threads + drag-and-drop (Task 3).

The console pipeline (``/console/pipeline``) used to read the stale agent-service
``/threads`` route and group cards into traffic-light columns. It now reads the
canonical ``apps.crm.OutreachThread`` rows grouped into the SAME ordered stage
columns Joseph's board uses (Discover -> Committed + a catch-all "Other"), and
the cards are draggable: a drop POSTs the thread id + the destination column's
stage to the single shared ``crm:thread-set-stage`` endpoint (Task 2). No
agent-service call happens. CSP-safe: SortableJS (jsdelivr) + a nonce'd init.
"""
import pytest
from django.test import Client
from django.contrib.auth import get_user_model
from django.utils import timezone


@pytest.fixture
def staff_client(db):
    """A staff user passes ``_can_manage_crm`` (the CRM gate the console reuses)."""
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
    """An ordinary workspace member — must be 403'd from the CRM pipeline."""
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


@pytest.mark.django_db
def test_pipeline_renders_crm_threads_grouped_by_stage(staff_client, crm_thread, monkeypatch):
    """The board shows the CRM thread's org, bucketed under its stage column —
    not the old agent-service traffic-light columns."""
    from apps.intelligence import console_views

    # Guard: agent-service must NOT be touched. Blow up if it is.
    monkeypatch.setattr(
        console_views, "safe_get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("agent-service called")),
    )

    resp = staff_client.get("/console/pipeline")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "AfDB" in body
    # Stage columns (Joseph parity), NOT traffic-light columns.
    assert "Proposal" in body
    assert "Discover" in body
    assert "Committed" in body


@pytest.mark.django_db
def test_pipeline_does_not_call_agent_service(staff_client, crm_thread, monkeypatch):
    """The repoint removed the ``safe_get('/threads')`` read entirely."""
    from apps.intelligence import console_views

    calls = []
    monkeypatch.setattr(console_views, "safe_get",
                        lambda *a, **k: calls.append(a) or {"items": []})

    resp = staff_client.get("/console/pipeline")
    assert resp.status_code == 200
    assert calls == []


@pytest.mark.django_db
def test_pipeline_wires_drag_drop_to_set_stage(staff_client, crm_thread):
    """The cards are draggable and a drop POSTs to the shared set_stage endpoint:
    SortableJS is loaded (jsdelivr) and the card carries its thread id + the
    destination column carries its stage key."""
    resp = staff_client.get("/console/pipeline")
    body = resp.content.decode()
    assert "cdn.jsdelivr.net" in body and "Sortable" in body
    assert "/crm/threads/" in body and "/stage/" in body
    assert f'data-thread-id="{crm_thread.id}"' in body
    assert 'data-stage="proposal"' in body  # the thread's display column


@pytest.mark.django_db
def test_pipeline_init_script_is_nonced(staff_client, crm_thread):
    """CSP-safe: the drag-drop init runs from a nonce'd <script>, no inline
    onclick/onsubmit handlers."""
    resp = staff_client.get("/console/pipeline")
    body = resp.content.decode()
    assert 'nonce="' in body
    assert "onclick=" not in body and "onsubmit=" not in body


@pytest.mark.django_db
def test_pipeline_forbidden_for_non_crm_role(member_client, crm_thread):
    """A plain workspace member is gated out of the CRM pipeline."""
    resp = member_client.get("/console/pipeline")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_pipeline_empty_db_renders_columns(staff_client):
    """An empty CRM just renders empty stage columns — never a 500."""
    resp = staff_client.get("/console/pipeline")
    assert resp.status_code == 200
    assert "Discover" in resp.content.decode()


@pytest.fixture
def owned_threads(db):
    """Two CRM threads owned by two different users, across two tracks — to
    exercise the Team board's Owner badge + owner/track filter chips."""
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.crm.models import Organization, OutreachThread

    alice = User.objects.create_user(
        email="alice-pl@x.io", password="pw", name="Alice Owner",
        tos_accepted_at=timezone.now(),
    )
    bob = User.objects.create_user(
        email="bob-pl@x.io", password="pw", name="Bob Owner",
        tos_accepted_at=timezone.now(),
    )
    org_a = Organization.objects.create(name="GreenClimate")
    org_b = Organization.objects.create(name="WorldBank")
    ta = OutreachThread.objects.create(
        org=org_a, owner=alice, stage=OutreachThread.Stage.ENGAGED,
        track="ai10bn", traffic_light="green", quintile=5,
    )
    tb = OutreachThread.objects.create(
        org=org_b, owner=bob, stage=OutreachThread.Stage.PROPOSAL,
        track="energy", traffic_light="amber", quintile=3,
    )
    return {"alice": alice, "bob": bob, "ta": ta, "tb": tb}


@pytest.mark.django_db
def test_console_pipeline_is_the_team_board(staff_client, owned_threads):
    """/console/pipeline is the Team board: a 'Team pipeline' header (not Joseph's
    'My pipeline') and an Owner badge on every card naming who owns the thread."""
    resp = staff_client.get("/console/pipeline")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Team pipeline" in body
    assert "My pipeline" not in body
    # Owner badge names the owner on each card.
    assert "Alice Owner" in body
    assert "Bob Owner" in body


@pytest.mark.django_db
def test_console_pipeline_has_owner_and_track_filter_chips(staff_client, owned_threads):
    """The Team board exposes owner + track filter chips (?owner= / ?track=) that
    narrow the visible threads to the selected owner/track."""
    alice = owned_threads["alice"]
    # owner filter chips reference ?owner=<id> for each owner
    resp = staff_client.get("/console/pipeline")
    body = resp.content.decode()
    assert f"owner={alice.id}" in body
    assert "track=ai10bn" in body or "track=energy" in body

    # Filtering by Alice's id drops Bob's thread.
    resp = staff_client.get(f"/console/pipeline?owner={alice.id}")
    body = resp.content.decode()
    assert "GreenClimate" in body
    assert "WorldBank" not in body


@pytest.mark.django_db
def test_console_pipeline_track_filter_narrows(staff_client, owned_threads):
    """Filtering by track narrows the board to that track's threads."""
    resp = staff_client.get("/console/pipeline?track=energy")
    body = resp.content.decode()
    assert "WorldBank" in body
    assert "GreenClimate" not in body


@pytest.mark.django_db
def test_notification_read_posts(staff_client, monkeypatch):
    from apps.intelligence import console_views
    calls = {}
    monkeypatch.setattr(console_views, "agent_post",
                        lambda path, json=None: calls.setdefault("path", path) or {})
    resp = staff_client.post("/console/notifications/n1/read")
    assert resp.status_code in (302, 303) and calls["path"] == "/notifications/n1/read"
