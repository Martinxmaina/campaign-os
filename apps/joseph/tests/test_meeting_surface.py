"""Tests for the meeting-loop surface wiring (TB.4, Task 7).

Task 7 stitches the capture loop into Joseph's existing surfaces, no new
endpoints:

- the **Today** strip shows a linked meeting's prep status + an "I'm going in"
  link straight into ``/joseph/capture/<thread_id>/`` (carrying the event id),
  and an event that has ended with no capture shows a "Capture now" entry;
- the **thread drawer** gains a "Meetings" section listing that thread's
  ``ExtractedMeeting`` rows, each linking to its confirm screen
  (``/joseph/meeting/<id>/``);
- Joseph's **action queue** (``JosephIntelligence.proposals``) merges in a
  pending-confirm ``ExtractedMeeting`` and a linkage suggestion as ActionCards.

Every page stays 200, role-gated by ``_can_access_joseph``, and CSP-safe (no
inline onclick/onsubmit; nonce on every non-src <script>).
"""
import re
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone


# --------------------------------------------------------------------------
# fixtures (reuse the established joseph/owner pattern)
# --------------------------------------------------------------------------


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
    """An ordinary workspace member (viewer) — must not reach the surface."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


def _thread(*, owner=None, org_name="Rockefeller Foundation", track="energy"):
    from apps.crm.models import Organization, OutreachThread

    org = Organization.objects.create(name=org_name)
    return OutreachThread.objects.create(org=org, track=track, owner=owner)


def _linked_event(workspace, thread, *, ended_min_ago=None, capture_status="none",
                  briefing_status="briefed", gid="surf1"):
    """A linked CalendarEvent starting today (so it lands on the Today strip).

    ``ended_min_ago`` ends it in the past; otherwise it is still upcoming today.
    """
    from apps.joseph.models import CalendarEvent

    now = timezone.now()
    end = now - timedelta(minutes=ended_min_ago) if ended_min_ago is not None else now + timedelta(minutes=30)
    start = end - timedelta(hours=1)
    return CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id=gid,
        title=f"{thread.org.name} sync",
        start=start,
        end=end,
        linked_thread_id=str(thread.id),
        briefing_status=briefing_status,
        capture_status=capture_status,
    )


def _meeting(thread, *, status=None):
    from apps.joseph.models import ExtractedMeeting

    return ExtractedMeeting.objects.create(
        thread=thread,
        source=ExtractedMeeting.Source.VOICE,
        transcript="t",
        status=status or ExtractedMeeting.Status.PENDING,
    )


def _no_agent():
    """Patch the agent-service-backed readers the home view touches to empty."""
    return [
        patch("apps.joseph.views.readers.list_threads", return_value=[]),
        patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]),
    ]


def _assert_csp_safe(body: str):
    assert "onclick=" not in body
    assert "onsubmit=" not in body
    for tag in re.findall(r"<script\b[^>]*>", body):
        # external scripts and json_script data islands carry no inline JS to gate.
        if "src=" in tag or 'type="application/json"' in tag:
            continue
        assert "nonce=" in tag


# --------------------------------------------------------------------------
# Today strip — linked meeting prep status + "I'm going in" → capture
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_today_linked_meeting_shows_going_in_to_capture(joseph, client, workspace):
    thread = _thread(owner=joseph)
    _linked_event(workspace, thread)
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = client.get(reverse("joseph:home") + "?view=desktop")
    assert resp.status_code == 200
    body = resp.content.decode()
    # the "I'm going in" CTA points at the capture surface for the linked thread
    assert reverse("joseph:capture", args=[str(thread.id)]) in body
    _assert_csp_safe(body)


@pytest.mark.django_db
def test_today_linked_meeting_shows_prep_status(joseph, client, workspace):
    thread = _thread(owner=joseph)
    _linked_event(workspace, thread, briefing_status="briefed")
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = client.get(reverse("joseph:home") + "?view=desktop")
    body = resp.content.decode()
    assert "Briefed" in body


@pytest.mark.django_db
def test_today_ended_meeting_no_capture_shows_capture_now(joseph, client, workspace):
    thread = _thread(owner=joseph)
    _linked_event(workspace, thread, ended_min_ago=10, capture_status="none")
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = client.get(reverse("joseph:home") + "?view=desktop")
    body = resp.content.decode()
    assert "Capture now" in body
    assert reverse("joseph:capture", args=[str(thread.id)]) in body


@pytest.mark.django_db
def test_today_captured_meeting_does_not_show_capture_now(joseph, client, workspace):
    thread = _thread(owner=joseph)
    _linked_event(workspace, thread, ended_min_ago=10, capture_status="captured")
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = client.get(reverse("joseph:home") + "?view=desktop")
    body = resp.content.decode()
    assert "Capture now" not in body


@pytest.mark.django_db
def test_today_mobile_shows_capture_entry(joseph, client, workspace):
    thread = _thread(owner=joseph)
    _linked_event(workspace, thread, ended_min_ago=10, capture_status="none")
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = client.get(reverse("joseph:home") + "?view=mobile")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Capture now" in body
    assert reverse("joseph:capture", args=[str(thread.id)]) in body
    _assert_csp_safe(body)


# --------------------------------------------------------------------------
# thread drawer — "Meetings" section lists ExtractedMeetings → confirm screen
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_drawer_lists_extracted_meetings_with_confirm_link(joseph, client, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    with patch("apps.joseph.views.readers.get_dossier", return_value={}):
        resp = client.get(reverse("joseph:thread", args=[str(thread.id)]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert reverse("joseph:meeting", args=[str(meeting.id)]) in body
    _assert_csp_safe(body)


@pytest.mark.django_db
def test_drawer_meetings_section_empty_state_no_meetings(joseph, client, workspace):
    thread = _thread(owner=joseph)
    with patch("apps.joseph.views.readers.get_dossier", return_value={}):
        resp = client.get(reverse("joseph:thread", args=[str(thread.id)]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_drawer_role_gated(viewer, client, workspace):
    thread = _thread()
    _meeting(thread)
    resp = client.get(reverse("joseph:thread", args=[str(thread.id)]))
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# action queue / proposals — pending-confirm meeting + linkage suggestion
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_proposals_surfaces_pending_confirm_meeting(joseph, client, workspace):
    from apps.joseph.intelligence import JosephIntelligence

    thread = _thread(owner=joseph)
    meeting = _meeting(thread, status=None)  # pending
    # a confirmed meeting must NOT appear
    from apps.joseph.models import ExtractedMeeting

    _meeting(thread, status=ExtractedMeeting.Status.CONFIRMED)
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        cards = JosephIntelligence().proposals(workspace=workspace, user=joseph)
    confirm_href = reverse("joseph:meeting", args=[str(meeting.id)])
    meeting_cards = [c for c in cards if c.get("kind") == "meeting_confirm"]
    assert len(meeting_cards) == 1
    assert meeting_cards[0]["href"] == confirm_href


@pytest.mark.django_db
def test_proposals_surfaces_linkage_suggestion(joseph, client, workspace):
    from apps.joseph.intelligence import JosephIntelligence
    from apps.joseph.models import CalendarEvent

    CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id="unlinked1",
        title="Mystery sync",
        start=timezone.now() + timedelta(days=1),
        linked_thread_id="",
    )
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        cards = JosephIntelligence().proposals(workspace=workspace, user=joseph)
    assert any(c.get("kind") == "calendar_link" for c in cards)


@pytest.mark.django_db
def test_home_renders_pending_meeting_in_action_queue(joseph, client, workspace):
    thread = _thread(owner=joseph)
    meeting = _meeting(thread)
    with patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]):
        resp = client.get(reverse("joseph:home") + "?view=desktop")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert reverse("joseph:meeting", args=[str(meeting.id)]) in body
