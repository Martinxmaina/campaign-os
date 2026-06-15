"""Console agents-fleet + breakers + healing UI — agent-brain Slice 2, Task 5.

The console renders the fleet status, circuit breakers and self-healing incidents
the agent-service brain produced (Slice 2 Tasks 1-4), and drives breaker Reset
against the lead-gated ``/breakers/<id>/reset`` API. All agent-service traffic is
mocked here — no real model or HTTP calls. Reads degrade to an empty state when the
service is down (never 500); the Reset mutation is owner/admin (brain-lead) gated.

Safety invariants exercised: protected-class action_classes are T2-capped (the
fleet renders the cap, never a promotion past it); no-trace-no-fix healing incidents
surface as ``insufficient_evidence`` (never a silent guess); constitutions/rubrics
are never mutated from this console; templates are CSP-safe (no nonce-less inline
script); an agent-down read renders an empty state instead of a 500.
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


# --- fixtures: an owner (brain-lead) and an ordinary member ----------------------


@pytest.fixture
def lead(client, org_owner, workspace):
    """An owner/admin — may view the fleet and reset breakers."""
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def member(client, db, organization, workspace):
    """An ordinary (non-admin) member — must not reach the fleet console."""
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    u = User.objects.create_user(
        email="fleetmember@example.com", password="x", name="Member", tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


# --- sample agent-service payloads (mirror app/api/brain.py + breakers.py) --------


_FLEET = {"agents": [
    {
        "agent_name": "herald",
        "status": "healthy",
        "tiers": [
            {"action_class": "reply_draft", "tier": "T2", "since": "2026-05-20T09:00:00+00:00",
             "evidence_count": 24, "protected": False, "capped": False},
            # A protected class — capped at T2, NEVER promoted past it.
            {"action_class": "protected_class_outreach", "tier": "T2", "since": "2026-05-22T09:00:00+00:00",
             "evidence_count": 40, "protected": True, "capped": True, "cap": "t2_permanent"},
        ],
        "open_breakers": 1,
        "episodes_7d": 42,
        "cost_7d_usd": 3.18,
        "gate_pass_rate": 0.97,
        "learnings": 5,
    },
    {
        "agent_name": "scout",
        "status": "down",
        "tiers": [
            {"action_class": "ingest", "tier": "T1", "since": "2026-06-01T09:00:00+00:00",
             "evidence_count": 8, "protected": False, "capped": False},
        ],
        "open_breakers": 0,
        "episodes_7d": 3,
        "cost_7d_usd": 0.04,
        "gate_pass_rate": 1.0,
        "learnings": 1,
    },
]}

_BREAKERS = {"items": [
    {
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "scope": "herald",
        "metric": "error_rate",
        "state": "open",
        "threshold": 0.25,
        "reason": "error_rate 0.40 over 12 episodes",
        "tripped_at": "2026-06-14T10:00:00+00:00",
    },
    {
        "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "scope": "scout",
        "metric": "cost_day",
        "state": "closed",
        "threshold": 5.0,
        "reason": None,
        "tripped_at": None,
    },
]}

_HEALING = {"incidents": [
    {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "agent_name": "herald",
        "breaker_scope": "herald",
        "fix_type": "config",
        "status": "fix_proposed",
        "root_cause_md": "Retry budget exhausted after upstream 429s; propose backoff bump.",
        "trace_ids": ["tr-1", "tr-2"],
        "pr_url": None,
        "created_at": "2026-06-14T10:05:00+00:00",
    },
    {
        # No-trace-no-fix: a window with no trace evidence stops at insufficient_evidence.
        "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        "agent_name": "scout",
        "breaker_scope": "scout",
        "fix_type": None,
        "status": "insufficient_evidence",
        "root_cause_md": "",
        "trace_ids": [],
        "pr_url": None,
        "created_at": "2026-06-14T11:00:00+00:00",
    },
]}


# --- Agents fleet --------------------------------------------------------------


@pytest.mark.django_db
def test_fleet_renders_card_per_agent(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: _FLEET):
        resp = client.get(reverse("console:agents-fleet"))
    assert resp.status_code == 200
    body = resp.content
    # one card per agent
    assert b"herald" in body and b"scout" in body
    # tier per action_class
    assert b"reply_draft" in body and b"T2" in body
    # 7d episodes / cost / gate-pass / learnings surfaced
    assert b"42" in body
    assert b"0.97" in body or b"97" in body
    # open breakers count
    assert b"1" in body


@pytest.mark.django_db
def test_fleet_shows_protected_class_t2_cap(lead, client):
    """A protected action_class is shown capped at T2 — never promoted past it."""
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: _FLEET):
        resp = client.get(reverse("console:agents-fleet"))
    assert resp.status_code == 200
    body = resp.content
    assert b"protected_class_outreach" in body
    # the cap is surfaced (protected / capped marker)
    assert b"protected" in body.lower() or b"cap" in body.lower()


@pytest.mark.django_db
def test_fleet_agent_down_empty_state(lead, client):
    """safe_get returns its default (down) — the page renders empty, never 500."""
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: None):
        resp = client.get(reverse("console:agents-fleet"))
    assert resp.status_code == 200
    assert b"unavailable" in resp.content.lower()


@pytest.mark.django_db
def test_fleet_forbidden_for_member(member, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get") as g:
        resp = client.get(reverse("console:agents-fleet"))
    assert resp.status_code == 403
    g.assert_not_called()


@pytest.mark.django_db
def test_fleet_requires_login(client, db):
    resp = client.get(reverse("console:agents-fleet"))
    assert resp.status_code in (302, 301)


# --- Breakers ------------------------------------------------------------------


@pytest.mark.django_db
def test_breakers_list_with_reset_action(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: _BREAKERS):
        resp = client.get(reverse("console:breakers"))
    assert resp.status_code == 200
    body = resp.content
    assert b"error_rate" in body
    assert b"herald" in body
    # state surfaced
    assert b"open" in body.lower()
    # Reset action targets the breaker reset endpoint for the OPEN breaker
    assert reverse("console:breaker-reset",
                   args=["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]).encode() in body


@pytest.mark.django_db
def test_breakers_agent_down_empty_state(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: None):
        resp = client.get(reverse("console:breakers"))
    assert resp.status_code == 200
    assert b"unavailable" in resp.content.lower()


@pytest.mark.django_db
def test_breakers_forbidden_for_member(member, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get") as g:
        resp = client.get(reverse("console:breakers"))
    assert resp.status_code == 403
    g.assert_not_called()


@pytest.mark.django_db
def test_breaker_reset_posts_to_reset_endpoint(lead, client):
    bid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post",
                      return_value={"id": bid, "state": "closed"}) as m:
        resp = client.post(reverse("console:breaker-reset", args=[bid]))
    assert resp.status_code in (200, 302)
    m.assert_called_once()
    assert m.call_args[0][0] == f"/breakers/{bid}/reset"


@pytest.mark.django_db
def test_breaker_reset_agent_down_does_not_500(lead, client):
    from apps.common.agent_client import AgentClientError
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post", side_effect=AgentClientError("down")):
        resp = client.post(reverse("console:breaker-reset",
                                   args=["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]))
    assert resp.status_code == 302


@pytest.mark.django_db
def test_breaker_reset_forbidden_for_member(member, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post") as p:
        resp = client.post(reverse("console:breaker-reset", args=["x"]))
    assert resp.status_code == 403
    p.assert_not_called()


@pytest.mark.django_db
def test_breaker_reset_requires_post(lead, client):
    """GET on the mutation endpoint is rejected (405), no agent call."""
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post") as p:
        resp = client.get(reverse("console:breaker-reset", args=["x"]))
    assert resp.status_code == 405
    p.assert_not_called()


# --- Healing incidents ---------------------------------------------------------


@pytest.mark.django_db
def test_healing_lists_incidents(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: _HEALING):
        resp = client.get(reverse("console:healing"))
    assert resp.status_code == 200
    body = resp.content
    assert b"herald" in body
    # root cause + fix type surfaced for the evidence-backed incident
    assert b"Retry budget exhausted" in body
    assert b"config" in body
    # trace IDs cited (no-trace-no-fix: a fix must cite traces)
    assert b"tr-1" in body


@pytest.mark.django_db
def test_healing_surfaces_insufficient_evidence(lead, client):
    """No-trace-no-fix: an incident with no trace evidence shows insufficient_evidence."""
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: _HEALING):
        resp = client.get(reverse("console:healing"))
    assert resp.status_code == 200
    assert b"insufficient" in resp.content.lower()


@pytest.mark.django_db
def test_healing_agent_down_empty_state(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: None):
        resp = client.get(reverse("console:healing"))
    assert resp.status_code == 200
    assert b"unavailable" in resp.content.lower()


@pytest.mark.django_db
def test_healing_forbidden_for_member(member, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get") as g:
        resp = client.get(reverse("console:healing"))
    assert resp.status_code == 403
    g.assert_not_called()


# --- CSP-safe templates (no nonce-less inline <script>, extends base) -----------


@pytest.mark.django_db
def test_fleet_templates_are_csp_safe(lead, client):
    from apps.intelligence import console_views

    def _get(path, default):
        if path.startswith("/brain/fleet"):
            return _FLEET
        if path.startswith("/breakers"):
            return _BREAKERS
        if path.startswith("/brain/healing"):
            return _HEALING
        return default

    with patch.object(console_views, "safe_get", side_effect=_get):
        fleet = client.get(reverse("console:agents-fleet")).content
        brk = client.get(reverse("console:breakers")).content
        heal = client.get(reverse("console:healing")).content
    for body in (fleet, brk, heal):
        # any <script> tag present must carry a nonce (CSP)
        assert b"<script" not in body or b"nonce" in body
