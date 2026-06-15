"""Tests for Task 8 — thread send + sequence enroll + triage queue + suppression
+ unsubscribe UI.

Five role-gated surfaces (plus one public one) over the outreach engine:

  * **Thread send.** ``POST /outreach/threads/<id>/send/`` (subject + body) runs the
    GATE INVARIANT: the body is gated (mock) and only a ``pass`` reaches the
    deliverability adapter ``guarded_send`` (mock) — which writes a
    ``crm.Activity(email_sent)``. A blocked body never reaches the transport and
    surfaces an approval-needed message (no 500).

  * **Sequence enroll.** ``POST /outreach/threads/<id>/enroll/`` (template) creates a
    ``Sequence`` + its ``SequenceStep`` rows for the thread.

  * **Triage queue.** ``GET /outreach/triage/`` lists the reply-triage items (threads
    with a recent ``email_reply`` Activity / paused sequences).

  * **Suppression list.** ``GET /outreach/suppression/`` lists entries; ``add``/``remove``
    POST actions mutate the list.

  * **Unsubscribe (PUBLIC).** ``GET /unsubscribe/<token>/`` — no auth — verifies the
    signed token and adds a ``SuppressionEntry`` for the encoded address.

All network (the gate client + the Gmail transport) is mocked — no real send ever
happens. CSP-safe: rendered pages carry no inline ``onclick``/``onsubmit`` handlers.
"""
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from django.utils import timezone


# ---------------------------------------------------------------------------
# Role fixtures (mirror test_mailbox_views.py).
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(client, org_owner, workspace):
    """A workspace owner — passes ``_can_manage_outreach``."""
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
    """An ordinary member (viewer) — must be 403'd from the outreach surfaces."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

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
def thread(db, org_owner):
    """A thread with an org + emailed primary contact, owned by org_owner."""
    from apps.crm.models import Contact, Organization, OutreachThread

    org = Organization.objects.create(name="Acme Capital")
    contact = Contact.objects.create(
        org=org, full_name="Pat Lee", email="pat@acme.org"
    )
    return OutreachThread.objects.create(
        org=org, primary_contact=contact, track="ai10bn", owner=org_owner,
    )


@pytest.fixture
def mailbox(db, org_owner):
    """An active mailbox for org_owner (no integration → scope guard skipped)."""
    from apps.outreach.models import Mailbox

    return Mailbox.objects.create(
        user=org_owner, email="joseph@africacen.org", daily_cap=50,
        ramp_started_at=timezone.now(),
    )


# ---------------------------------------------------------------------------
# Thread send — gate-on-send invariant + Activity
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_thread_send_gates_then_sends_and_logs_activity(manager, client, thread, mailbox):
    """A pass verdict flows through guarded_send → email_sent Activity, 200/302."""
    from apps.crm.models import Activity

    sender = MagicMock()
    sender.send.return_value = "msg-abc"
    with patch(
        "apps.outreach.gating.check_gate",
        return_value={"verdict": "pass", "findings": [], "gate_id": "g-99"},
    ), patch("apps.outreach.views_thread._build_sender", return_value=sender):
        resp = client.post(
            reverse("outreach:thread-send", args=[thread.id]),
            {"subject": "Hello Pat", "body": "<p>Quick intro</p>"},
        )

    assert resp.status_code in (200, 302)
    sender.send.assert_called_once()
    act = Activity.objects.filter(thread=thread, activity_type="email_sent").first()
    assert act is not None
    assert act.content_ref.get("gate_id") == "g-99"
    assert act.content_ref.get("message_id") == "msg-abc"


@pytest.mark.django_db
def test_thread_send_blocked_body_never_reaches_transport(manager, client, thread, mailbox):
    """A non-pass verdict: the transport is NEVER called; an approval is queued."""
    from apps.crm.models import Activity

    sender = MagicMock()
    findings = [{"rule": "token_language", "match": "guaranteed returns"}]
    with patch(
        "apps.outreach.gating.check_gate",
        return_value={"verdict": "block", "findings": findings, "gate_id": "g-x"},
    ), patch("apps.outreach.views_thread._build_sender", return_value=sender):
        resp = client.post(
            reverse("outreach:thread-send", args=[thread.id]),
            {"subject": "Bad", "body": "<p>guaranteed returns</p>"},
        )

    # No 500 — the block is handled and surfaced to the operator.
    assert resp.status_code in (200, 302)
    sender.send.assert_not_called()
    assert not Activity.objects.filter(thread=thread, activity_type="email_sent").exists()
    # An approval-needed record exists for review.
    assert Activity.objects.filter(
        thread=thread, activity_type="email_gate_blocked"
    ).exists()


@pytest.mark.django_db
def test_thread_send_forbidden_for_viewer(viewer, client, thread):
    resp = client.post(
        reverse("outreach:thread-send", args=[thread.id]),
        {"subject": "s", "body": "<p>h</p>"},
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_thread_send_requires_post(manager, client, thread):
    resp = client.get(reverse("outreach:thread-send", args=[thread.id]))
    assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Sequence enroll — creates a Sequence + steps
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_thread_enroll_creates_sequence_with_steps(manager, client, thread):
    from apps.outreach.models import Sequence, SequenceStep, SequenceTemplate

    tmpl = SequenceTemplate.objects.create(
        name="3-touch",
        steps=[
            {"kind": "email", "delay_days": 0, "subject": "Intro", "body": "<p>hi</p>"},
            {"kind": "email", "delay_days": 3, "subject": "Bump", "body": "<p>still?</p>"},
            {"kind": "linkedin", "delay_days": 5, "subject": "", "body": "connect"},
        ],
    )
    resp = client.post(
        reverse("outreach:thread-enroll", args=[thread.id]),
        {"template": str(tmpl.id)},
    )
    assert resp.status_code in (200, 302)
    seq = Sequence.objects.filter(thread=thread).first()
    assert seq is not None
    assert SequenceStep.objects.filter(sequence=seq).count() == 3


@pytest.mark.django_db
def test_thread_enroll_forbidden_for_viewer(viewer, client, thread):
    from apps.outreach.models import SequenceTemplate

    tmpl = SequenceTemplate.objects.create(name="x", steps=[])
    resp = client.post(
        reverse("outreach:thread-enroll", args=[thread.id]),
        {"template": str(tmpl.id)},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Triage queue — lists reply-triage items
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_triage_queue_lists_reply_items(manager, client, thread):
    from apps.crm.models import Activity

    Activity.objects.create(
        thread=thread,
        activity_type="email_reply",
        actor_type="agent",
        agent_name="outreach",
        content_ref={"from": "pat@acme.org", "subject": "Re: Hello"},
    )
    resp = client.get(reverse("outreach:triage"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Acme Capital" in body
    assert "onclick=" not in body
    assert "onsubmit=" not in body


@pytest.mark.django_db
def test_triage_queue_forbidden_for_viewer(viewer, client):
    resp = client.get(reverse("outreach:triage"))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Suppression list — list + add + remove
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_suppression_list_renders(manager, client):
    from apps.outreach.models import SuppressionEntry

    SuppressionEntry.objects.create(email="optout@x.org", reason="unsubscribe")
    resp = client.get(reverse("outreach:suppression"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "optout@x.org" in body
    assert "onclick=" not in body
    assert "onsubmit=" not in body


@pytest.mark.django_db
def test_suppression_add_creates_entry(manager, client):
    from apps.outreach.models import SuppressionEntry

    resp = client.post(
        reverse("outreach:suppression-add"),
        {"email": "New@Example.org", "reason": "bounce"},
    )
    assert resp.status_code in (200, 302)
    assert SuppressionEntry.objects.filter(email__iexact="new@example.org").exists()


@pytest.mark.django_db
def test_suppression_remove_deletes_entry(manager, client):
    from apps.outreach.models import SuppressionEntry

    entry = SuppressionEntry.objects.create(email="gone@x.org", reason="unsubscribe")
    resp = client.post(reverse("outreach:suppression-remove", args=[entry.id]))
    assert resp.status_code in (200, 302)
    assert not SuppressionEntry.objects.filter(id=entry.id).exists()


@pytest.mark.django_db
def test_suppression_forbidden_for_viewer(viewer, client):
    resp = client.get(reverse("outreach:suppression"))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Unsubscribe — PUBLIC (no auth), signed token → SuppressionEntry
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_unsubscribe_public_adds_suppression(client):
    """A valid signed token (no login) adds a SuppressionEntry for the address."""
    from apps.outreach.models import SuppressionEntry
    from apps.outreach.senders import make_unsubscribe_token

    token = make_unsubscribe_token("Bye@Acme.org")
    resp = client.get(reverse("outreach_public:unsubscribe", args=[token]))
    assert resp.status_code == 200
    assert SuppressionEntry.objects.filter(email__iexact="bye@acme.org").exists()


@pytest.mark.django_db
def test_unsubscribe_is_idempotent(client):
    """Hitting the same token twice does not error and keeps a single entry."""
    from apps.outreach.models import SuppressionEntry
    from apps.outreach.senders import make_unsubscribe_token

    token = make_unsubscribe_token("dup@acme.org")
    client.get(reverse("outreach_public:unsubscribe", args=[token]))
    resp = client.get(reverse("outreach_public:unsubscribe", args=[token]))
    assert resp.status_code == 200
    assert SuppressionEntry.objects.filter(email__iexact="dup@acme.org").count() == 1


@pytest.mark.django_db
def test_unsubscribe_bad_token_does_not_500(client):
    """A tampered/invalid token returns a graceful page (no crash), no entry added."""
    from apps.outreach.models import SuppressionEntry

    resp = client.get(reverse("outreach_public:unsubscribe", args=["not-a-valid-token"]))
    assert resp.status_code in (200, 400)
    assert SuppressionEntry.objects.count() == 0
