"""Tests for the pipeline drag-and-drop ``set_stage`` endpoint (Task 2).

Both pipelines (Joseph + console) read the same canonical Django threads
(``apps.crm.OutreachThread``) grouped by ``Stage`` and POST to a single
``set_stage`` endpoint when a card is dragged to a new stage column:

  POST /crm/threads/<id>/stage/   → set the thread's stage + log an Activity

The endpoint is role-gated (``_can_manage_crm`` / staff), validates the target
against ``OutreachThread.Stage`` (an unknown stage → 400, no change) and appends
an ``Activity(activity_type="stage_advanced")`` so a drag is never silent.
CSP-safe — the drag-drop is wired client-side with SortableJS + a CSRF-headered
``fetch``; there are no inline handlers to test here.
"""
import pytest
from django.urls import reverse


# ---------------------------------------------------------------------------
# Role fixtures (mirror test_thread_actions.py) — manager passes, viewer 403s.
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
    """An ordinary member (viewer) — must be 403'd from the stage endpoint."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    from django.utils import timezone

    u = User.objects.create_user(
        email="viewer-stage@example.com", password="x", name="Viewer",
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
    """A CRM org + contact + outreach thread (stage=engaged)."""
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
    )


# ---------------------------------------------------------------------------
# set_stage — the drag-and-drop write
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_set_stage_updates_stage_and_logs_activity(manager, client, thread):
    from apps.crm.models import Activity

    resp = client.post(
        reverse("crm:thread-set-stage", args=[thread.id]),
        {"stage": "proposal_sent"},
    )
    assert resp.status_code in (200, 204, 302)
    thread.refresh_from_db()
    assert thread.stage == "proposal_sent"

    acts = Activity.objects.filter(thread=thread, activity_type="stage_advanced")
    assert acts.count() == 1
    a = acts.first()
    assert a.actor_id == manager.id
    assert a.actor_type == "human"
    assert a.content_ref.get("from") == "engaged"
    assert a.content_ref.get("to") == "proposal_sent"


@pytest.mark.django_db
def test_set_stage_forbidden_for_viewer(viewer, client, thread):
    from apps.crm.models import Activity

    resp = client.post(
        reverse("crm:thread-set-stage", args=[thread.id]),
        {"stage": "closed"},
    )
    assert resp.status_code == 403
    thread.refresh_from_db()
    assert thread.stage == "engaged"  # unchanged
    assert not Activity.objects.filter(thread=thread).exists()


@pytest.mark.django_db
def test_set_stage_invalid_stage_is_400_no_change(manager, client, thread):
    from apps.crm.models import Activity

    resp = client.post(
        reverse("crm:thread-set-stage", args=[thread.id]),
        {"stage": "not_a_real_stage"},
    )
    assert resp.status_code == 400
    thread.refresh_from_db()
    assert thread.stage == "engaged"  # unchanged
    assert not Activity.objects.filter(thread=thread).exists()


@pytest.mark.django_db
def test_set_stage_missing_stage_is_400(manager, client, thread):
    resp = client.post(
        reverse("crm:thread-set-stage", args=[thread.id]),
        {},
    )
    assert resp.status_code == 400
    thread.refresh_from_db()
    assert thread.stage == "engaged"


@pytest.mark.django_db
def test_set_stage_same_stage_no_activity(manager, client, thread):
    """Dropping a card back in its own column is a harmless no-op — no Activity
    row (a stage didn't actually advance)."""
    from apps.crm.models import Activity

    resp = client.post(
        reverse("crm:thread-set-stage", args=[thread.id]),
        {"stage": "engaged"},
    )
    assert resp.status_code in (200, 204, 302)
    thread.refresh_from_db()
    assert thread.stage == "engaged"
    assert not Activity.objects.filter(thread=thread, activity_type="stage_advanced").exists()


# ---------------------------------------------------------------------------
# End-to-end: the keys the pipeline TEMPLATE actually emits (data-stage) must
# move the stage. The board's columns are DISPLAY keys (discover/qualify/
# proposal/diligence/committed), not raw Stage values — every drop onto one of
# them must resolve to a real Stage, not 400 + a reverted card. This is the
# regression the raw-Stage tests above missed.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("column_key", "expected_stage"),
    [
        ("discover", "targeted"),
        ("qualify", "engaged"),
        ("proposal", "proposal_sent"),
        ("diligence", "in_discussion"),
        ("committed", "committed"),
    ],
)
def test_set_stage_accepts_pipeline_column_keys(
    manager, client, thread, column_key, expected_stage
):
    """Posting a ``_PIPELINE_STAGES`` column key (what the template emits in
    ``data-stage``) resolves to the canonical Stage and advances the thread —
    not a 400 that the JS onEnd handler would revert."""
    from apps.crm.models import Activity

    # Start from a stage distinct from each target so every drop is a real move.
    thread.stage = "closed"
    thread.save(update_fields=["stage"])

    resp = client.post(
        reverse("crm:thread-set-stage", args=[thread.id]),
        {"stage": column_key},
    )
    assert resp.status_code in (200, 204, 302), (
        f"column key {column_key!r} should be accepted, got {resp.status_code}"
    )
    thread.refresh_from_db()
    assert thread.stage == expected_stage

    a = Activity.objects.filter(thread=thread, activity_type="stage_advanced").first()
    assert a is not None
    assert a.content_ref.get("to") == expected_stage
