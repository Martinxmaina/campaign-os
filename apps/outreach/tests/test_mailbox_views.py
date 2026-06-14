"""Tests for Task 7 — gmail.send scope guard + mailbox connect/status UI.

Two surfaces under test:

  * **Scope guard (adapter).** ``guarded_send`` must fail with a clear,
    catchable error — ``MailboxScopeError`` — when the mailbox's connected
    ``GoogleIntegration`` was granted *without* the ``gmail.send`` scope, BEFORE
    the transport is ever touched (so a misconfigured grant can't 500 mid-send).

  * **Mailbox status view.** ``/outreach/mailbox/`` is role-gated
    (owner/admin/campaign_owner → 200, viewer → 403) and shows, per mailbox, the
    effective cap, the warm-up ramp week, today's send count and the global
    suppression count. ``pause``/``resume`` POST actions toggle ``Mailbox.status``.

All network is mocked — the Gmail transport is never called in these tests.
CSP-safe: the rendered page carries no inline ``onclick``/``onsubmit`` handlers.
"""
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from django.utils import timezone

from integrations.gmail import GMAIL_SEND_SCOPE


# ---------------------------------------------------------------------------
# Role fixtures (mirror apps/crm test_crm_views.py).
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
    """An ordinary member (viewer) — must be 403'd from the outreach surface."""
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
def seed_mailbox(db, org_owner):
    """A connected mailbox (GoogleIntegration WITH gmail.send) + some context."""
    from apps.joseph.models import GoogleIntegration
    from apps.outreach.models import Mailbox, MailboxSend, SuppressionEntry

    integ = GoogleIntegration.objects.create(
        user=org_owner,
        refresh_token="rt",
        scopes=["https://www.googleapis.com/auth/gmail.readonly", GMAIL_SEND_SCOPE],
    )
    mailbox = Mailbox.objects.create(
        user=org_owner, email="joseph@africacen.org", daily_cap=50,
        google_integration=integ, ramp_started_at=timezone.now(),
    )
    MailboxSend.objects.create(mailbox=mailbox, date=timezone.localdate(), count=7)
    SuppressionEntry.objects.create(email="optout@x.org", reason="unsubscribe")
    return mailbox


# ---------------------------------------------------------------------------
# Scope guard — guarded_send fails closed without gmail.send
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guarded_send_requires_gmail_send_scope():
    """A grant lacking gmail.send raises MailboxScopeError, transport untouched."""
    from apps.crm.models import Organization, OutreachThread
    from apps.joseph.models import GoogleIntegration
    from apps.outreach.exceptions import MailboxScopeError
    from apps.outreach.models import Mailbox
    from apps.outreach.senders import guarded_send

    from apps.accounts.models import User

    user = User.objects.create_user(
        email="owner@africacen.org", password="x", name="Owner",
        tos_accepted_at=timezone.now(),
    )
    # Connected, but the grant only has gmail.readonly — NOT gmail.send.
    integ = GoogleIntegration.objects.create(
        user=user, refresh_token="rt",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    mailbox = Mailbox.objects.create(
        user=user, email="owner@africacen.org", google_integration=integ,
    )
    org = Organization.objects.create(name="Acme")
    thread = OutreachThread.objects.create(org=org, track="ai10bn")

    sender = MagicMock()
    with pytest.raises(MailboxScopeError):
        guarded_send(
            mailbox, to="a@b.org", subject="s", body="<p>h</p>",
            thread=thread, gate_id="g1", sender=sender,
        )
    # Fail closed — the transport is never reached.
    sender.send.assert_not_called()


@pytest.mark.django_db
def test_guarded_send_passes_when_scope_present():
    """A grant WITH gmail.send sends normally (scope guard does not block)."""
    from apps.crm.models import Activity, Organization, OutreachThread
    from apps.joseph.models import GoogleIntegration
    from apps.outreach.models import Mailbox, MailboxSend
    from apps.outreach.senders import guarded_send

    from apps.accounts.models import User

    user = User.objects.create_user(
        email="owner2@africacen.org", password="x", name="Owner2",
        tos_accepted_at=timezone.now(),
    )
    integ = GoogleIntegration.objects.create(
        user=user, refresh_token="rt", scopes=[GMAIL_SEND_SCOPE],
    )
    mailbox = Mailbox.objects.create(
        user=user, email="owner2@africacen.org", google_integration=integ,
    )
    org = Organization.objects.create(name="Beta")
    thread = OutreachThread.objects.create(org=org, track="ai10bn")

    sender = MagicMock()
    sender.send.return_value = "msg-123"
    mid = guarded_send(
        mailbox, to="a@b.org", subject="s", body="<p>h</p>",
        thread=thread, gate_id="g1", sender=sender,
    )
    assert mid == "msg-123"
    sender.send.assert_called_once()
    assert MailboxSend.objects.get(mailbox=mailbox).count == 1
    assert Activity.objects.filter(thread=thread, activity_type="email_sent").exists()


@pytest.mark.django_db
def test_guarded_send_allows_when_no_integration():
    """No connected integration → scope guard does not block (other tests/stubs)."""
    from apps.crm.models import Organization, OutreachThread
    from apps.outreach.models import Mailbox
    from apps.outreach.senders import guarded_send

    from apps.accounts.models import User

    user = User.objects.create_user(
        email="owner3@africacen.org", password="x", name="Owner3",
        tos_accepted_at=timezone.now(),
    )
    mailbox = Mailbox.objects.create(
        user=user, email="owner3@africacen.org", google_integration=None,
    )
    org = Organization.objects.create(name="Gamma")
    thread = OutreachThread.objects.create(org=org, track="ai10bn")

    sender = MagicMock()
    sender.send.return_value = "msg-9"
    mid = guarded_send(
        mailbox, to="a@b.org", subject="s", body="<p>h</p>",
        thread=thread, gate_id="g1", sender=sender,
    )
    assert mid == "msg-9"
    sender.send.assert_called_once()


# ---------------------------------------------------------------------------
# Mailbox status view — role gate + status data
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mailbox_status_renders_for_manager(manager, client, seed_mailbox):
    resp = client.get(reverse("outreach:mailbox"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "joseph@africacen.org" in body
    # Today's count (7), the suppression count (1), and the ramp/cap surface.
    assert "7" in body
    assert "1" in body
    # CSP-safe — no inline event handlers.
    assert "onclick=" not in body
    assert "onsubmit=" not in body


@pytest.mark.django_db
def test_mailbox_status_forbidden_for_viewer(viewer, client):
    resp = client.get(reverse("outreach:mailbox"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_mailbox_status_shows_cap_ramp_today_suppression(manager, client, seed_mailbox):
    """Context exposes effective cap, ramp week, today's count, suppression count."""
    resp = client.get(reverse("outreach:mailbox"))
    assert resp.status_code == 200
    rows = resp.context["mailboxes"]
    row = next(r for r in rows if r["mailbox"].email == "joseph@africacen.org")
    assert row["sent_today"] == 7
    assert row["ramp_week"] == 0
    assert row["effective_cap"] == 20  # week 0 ramp cap
    assert resp.context["suppression_count"] == 1


@pytest.mark.django_db
def test_mailbox_status_flags_missing_send_scope(manager, client, db, org_owner):
    """A mailbox connected without gmail.send is flagged as not send-ready."""
    from apps.joseph.models import GoogleIntegration
    from apps.outreach.models import Mailbox

    integ = GoogleIntegration.objects.create(
        user=org_owner, refresh_token="rt",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    Mailbox.objects.create(
        user=org_owner, email="noscope@africacen.org", google_integration=integ,
    )
    resp = client.get(reverse("outreach:mailbox"))
    assert resp.status_code == 200
    rows = resp.context["mailboxes"]
    row = next(r for r in rows if r["mailbox"].email == "noscope@africacen.org")
    assert row["can_send"] is False


# ---------------------------------------------------------------------------
# pause / resume — toggle Mailbox.status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mailbox_pause_sets_status_paused(manager, client, seed_mailbox):
    assert seed_mailbox.status == "active"
    resp = client.post(reverse("outreach:mailbox-pause", args=[seed_mailbox.id]))
    assert resp.status_code in (200, 302)
    seed_mailbox.refresh_from_db()
    assert seed_mailbox.status == "paused"


@pytest.mark.django_db
def test_mailbox_resume_sets_status_active(manager, client, seed_mailbox):
    from apps.outreach.models import Mailbox

    seed_mailbox.status = Mailbox.Status.PAUSED
    seed_mailbox.save(update_fields=["status"])
    resp = client.post(reverse("outreach:mailbox-resume", args=[seed_mailbox.id]))
    assert resp.status_code in (200, 302)
    seed_mailbox.refresh_from_db()
    assert seed_mailbox.status == "active"


@pytest.mark.django_db
def test_mailbox_pause_forbidden_for_viewer(viewer, client, db, org_owner):
    from apps.outreach.models import Mailbox

    mailbox = Mailbox.objects.create(user=org_owner, email="x@africacen.org")
    resp = client.post(reverse("outreach:mailbox-pause", args=[mailbox.id]))
    assert resp.status_code == 403
    mailbox.refresh_from_db()
    assert mailbox.status == "active"


@pytest.mark.django_db
def test_mailbox_pause_requires_post(manager, client, seed_mailbox):
    resp = client.get(reverse("outreach:mailbox-pause", args=[seed_mailbox.id]))
    assert resp.status_code == 405
