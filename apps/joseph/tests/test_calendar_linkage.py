"""Tests for Calendar ↔ thread auto-linking + confirm-linkage (TB.3).

``linkage.match_event_to_thread`` token-set-matches a CalendarEvent's title +
attendees against the CRM Organization name + Contact email/name; a confident
(≥0.9) match auto-links via ``linkage.link_event`` while a 0.5–0.9 match is only
*suggested* (surfaced through ``JosephIntelligence._unlinked_calendar_events``),
never silently linked. The confirm route ``POST /joseph/calendar/<id>/link/``
lets the principal link a meeting to a thread by hand (role-gated, CSRF).
"""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.joseph import linkage
from apps.joseph.intelligence import JosephIntelligence
from apps.joseph.models import CalendarEvent


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
    """An ordinary workspace member (viewer) — must not reach the confirm route."""
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    u = User.objects.create_user(
        email="viewer@example.com", password="x", name="Viewer", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.filter(user=u).delete()
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


def _thread(*, org_name, contact_name="", contact_email=""):
    """Create a CRM OutreachThread (+ org, + optional primary contact)."""
    from apps.crm.models import Contact, Organization, OutreachThread

    org = Organization.objects.create(name=org_name)
    contact = None
    if contact_name or contact_email:
        contact = Contact.objects.create(org=org, full_name=contact_name, email=contact_email)
    return OutreachThread.objects.create(org=org, primary_contact=contact)


def _event(workspace, *, title, attendees=None, gid="g1"):
    return CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id=gid,
        title=title,
        start=timezone.now() + timedelta(days=1),
        attendees=attendees or [],
    )


# --------------------------------------------------------------------------
# new model fields
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_calendar_event_new_fields_defaults(workspace):
    """The cascade/capture fields land with safe defaults."""
    ev = _event(workspace, title="Sync")
    fetched = CalendarEvent.objects.get(pk=ev.pk)
    assert fetched.briefing_status == "none"
    assert fetched.talking_points == []
    assert fetched.prep_stages == []
    assert fetched.capture_status == "none"
    assert fetched.defer_until is None


# --------------------------------------------------------------------------
# match_event_to_thread — token-set match + confidence band
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_match_high_confidence_on_org_name_in_title(workspace):
    thread = _thread(org_name="Rockefeller Foundation")
    ev = _event(workspace, title="Rockefeller Foundation — climate sync")
    matched, confidence = linkage.match_event_to_thread(ev)
    assert matched is not None
    assert matched.id == thread.id
    assert confidence >= 0.9


@pytest.mark.django_db
def test_match_high_confidence_on_attendee_email(workspace):
    thread = _thread(org_name="Rockefeller Foundation", contact_email="officer@rockfound.org")
    # title is unrelated; the match must come from the attendee email vs contact email.
    ev = _event(
        workspace,
        title="Quarterly check-in",
        attendees=[{"email": "officer@rockfound.org"}],
    )
    matched, confidence = linkage.match_event_to_thread(ev)
    assert matched is not None
    assert matched.id == thread.id
    assert confidence >= 0.9


@pytest.mark.django_db
def test_match_no_match_returns_none(workspace):
    _thread(org_name="Rockefeller Foundation", contact_email="officer@rockfound.org")
    ev = _event(workspace, title="Dentist appointment", attendees=[{"email": "me@gmail.com"}])
    matched, confidence = linkage.match_event_to_thread(ev)
    assert matched is None
    assert confidence < 0.5


@pytest.mark.django_db
def test_match_mid_confidence_is_a_suggestion_not_a_match(workspace):
    """A 0.5–0.9 partial-name overlap is returned as a confidence but, at the
    default ≥0.9 threshold, is NOT a confident auto-link (matched is None)."""
    _thread(org_name="Rockefeller Brothers Fund")
    ev = _event(workspace, title="Rockefeller catch up")
    matched, confidence = linkage.match_event_to_thread(ev)
    # partial overlap → a mid-band score that does not clear the auto-link bar
    assert 0.5 <= confidence < 0.9
    assert matched is None


# --------------------------------------------------------------------------
# link_event — the setter
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_link_event_sets_thread_and_briefing_status(workspace):
    thread = _thread(org_name="GEAPP")
    ev = _event(workspace, title="GEAPP review")
    linkage.link_event(ev, thread)
    fetched = CalendarEvent.objects.get(pk=ev.pk)
    assert fetched.linked_thread_id == str(thread.id)
    assert fetched.briefing_status == "linked"


# --------------------------------------------------------------------------
# auto-link entry point — confident matches link, mid-band stays a suggestion
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_link_links_confident_match(workspace):
    thread = _thread(org_name="Rockefeller Foundation")
    ev = _event(workspace, title="Rockefeller Foundation — climate sync")
    linked = linkage.auto_link_event(ev)
    assert linked is not None
    ev.refresh_from_db()
    assert ev.linked_thread_id == str(thread.id)
    assert ev.briefing_status == "linked"


@pytest.mark.django_db
def test_auto_link_leaves_mid_band_unlinked_as_suggestion(workspace):
    """A mid-band (0.5–0.9) match is NOT auto-linked but DOES surface as a
    linkage suggestion via the unlinked/suggestion seam."""
    _thread(org_name="Rockefeller Brothers Fund")
    ev = _event(workspace, title="Rockefeller catch up")
    linked = linkage.auto_link_event(ev)
    assert linked is None
    ev.refresh_from_db()
    assert ev.linked_thread_id == ""

    suggestions = JosephIntelligence()._unlinked_calendar_events(workspace)
    ids = {s["id"] for s in suggestions}
    assert ev.google_event_id in ids


# --------------------------------------------------------------------------
# confirm route — POST /joseph/calendar/<google_event_id>/link/
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_confirm_link_route_links_event(joseph, client, workspace):
    thread = _thread(org_name="GIZ")
    ev = _event(workspace, title="Unlinked meeting")
    url = reverse("joseph:calendar-link", kwargs={"google_event_id": ev.google_event_id})
    resp = client.post(url, {"thread_id": str(thread.id)})
    assert resp.status_code in (200, 302)
    ev.refresh_from_db()
    assert ev.linked_thread_id == str(thread.id)
    assert ev.briefing_status == "linked"


@pytest.mark.django_db
def test_confirm_link_route_role_gated(viewer, client, workspace):
    thread = _thread(org_name="GIZ")
    ev = _event(workspace, title="Unlinked meeting")
    url = reverse("joseph:calendar-link", kwargs={"google_event_id": ev.google_event_id})
    resp = client.post(url, {"thread_id": str(thread.id)})
    assert resp.status_code == 403
    ev.refresh_from_db()
    assert ev.linked_thread_id == ""


@pytest.mark.django_db
def test_confirm_link_route_requires_post(joseph, client, workspace):
    ev = _event(workspace, title="Unlinked meeting")
    url = reverse("joseph:calendar-link", kwargs={"google_event_id": ev.google_event_id})
    resp = client.get(url)
    assert resp.status_code == 405


@pytest.mark.django_db
def test_confirm_link_route_unknown_thread_links_nothing(joseph, client, workspace):
    ev = _event(workspace, title="Unlinked meeting")
    url = reverse("joseph:calendar-link", kwargs={"google_event_id": ev.google_event_id})
    resp = client.post(url, {"thread_id": "00000000-0000-0000-0000-000000000000"})
    assert resp.status_code in (200, 302, 404)
    ev.refresh_from_db()
    assert ev.linked_thread_id == ""
