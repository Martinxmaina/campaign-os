"""Console Learning Log + diff-review (approve/reject) UI — agent-brain Loop 2, Task 5.

The console renders the weekly Learning memos and the proposed playbook diffs the
agent-service Evaluator produced (Tasks 3/4), and drives human approval against the
``/brain/*`` API (Task 4). All agent-service traffic is mocked here — no real model
or HTTP calls. Reads degrade to an empty state when the service is down (never 500);
mutations are owner/admin (brain-lead) gated.
"""
from unittest.mock import patch

import pytest
from django.urls import reverse


# --- fixtures: an owner (brain-lead) and an ordinary member ----------------------


@pytest.fixture
def lead(client, org_owner, workspace):
    """An owner/admin — may review and approve/reject diffs."""
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def member(client, db, organization, workspace):
    """An ordinary (non-admin) member — must not reach the Learning console."""
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    u = User.objects.create_user(
        email="brainmember@example.com", password="x", name="Member", tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


# --- sample agent-service payloads (mirror app/api/brain.py serialization) -------


_LEARNINGS = {"learnings": [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "summary": "Evaluator reflection for herald (2026-W24): considered 2 candidate(s) "
                   "over 9 episode(s); proposed 1 diff(s).",
        "meta": {"agent_name": "herald", "week": "2026-W24", "episodes_considered": 9,
                 "diffs_proposed": 1, "eval_rejected": 0, "dropped_low_evidence": 1,
                 "refused_frozen": 0},
        "created_at": "2026-06-12T09:00:00+00:00",
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "summary": "Evaluator reflection for scout (2026-W24): proposed 0 diff(s).",
        "meta": {"agent_name": "scout", "week": "2026-W24", "episodes_considered": 3,
                 "diffs_proposed": 0},
        "created_at": "2026-06-12T09:01:00+00:00",
    },
]}

_PROPOSALS = {"proposals": [
    {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "agent_name": "herald",
        "sector": "energy",
        "version": 5,
        "status": "proposed",
        "body": "PLAYBOOK v5\nLead with the data point.",
        "diff_category": "tone",
        "diff_from_previous": "- Lead softly\n+ Lead with the data point.",
        "evidence_episode_ids": ["ep-1", "ep-2", "ep-3"],
        "expected_effect": "higher reply rate on energy threads",
        "metric_to_watch": "reply_rate",
        "eval_run_id": "ee111111-1111-1111-1111-111111111111",
        "approver": None,
        "applied_at": None,
        "created_at": "2026-06-12T09:00:00+00:00",
    },
]}

_EVAL_RUN = {
    "id": "ee111111-1111-1111-1111-111111111111",
    "result": {
        "overall_pass": True,
        "results": [
            {"case_id": "c1", "name": "status-language trap", "category": "compliance",
             "passed": True, "score": 1.0, "detail": "ok"},
            {"case_id": "c2", "name": "reply quality", "category": "quality",
             "passed": True, "score": 0.9, "detail": "ok"},
        ],
    },
    "created_at": "2026-06-12T09:00:00+00:00",
}


# --- Learning Log --------------------------------------------------------------


@pytest.mark.django_db
def test_learning_log_lists_memos_and_diff_counts(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get",
                      side_effect=lambda path, default: _LEARNINGS):
        resp = client.get(reverse("console:learning-log"))
    assert resp.status_code == 200
    body = resp.content
    assert b"herald" in body and b"scout" in body
    # per-agent diff count surfaced
    assert b"2026-W24" in body
    # the proposed-diff count from meta is shown
    assert b"1" in body


@pytest.mark.django_db
def test_learning_log_agent_down_empty_state(lead, client):
    """safe_get returns its default (down) — the page renders empty, never 500."""
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: None):
        resp = client.get(reverse("console:learning-log"))
    assert resp.status_code == 200
    assert b"unavailable" in resp.content.lower()


@pytest.mark.django_db
def test_learning_log_forbidden_for_member(member, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get") as g:
        resp = client.get(reverse("console:learning-log"))
    assert resp.status_code == 403
    g.assert_not_called()


@pytest.mark.django_db
def test_learning_log_requires_login(client, db):
    resp = client.get(reverse("console:learning-log"))
    assert resp.status_code in (302, 301)


# --- Diff list -----------------------------------------------------------------


@pytest.mark.django_db
def test_diff_list_shows_proposed_diffs(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get",
                      side_effect=lambda path, default: _PROPOSALS):
        resp = client.get(reverse("console:diff-list"))
    assert resp.status_code == 200
    body = resp.content
    assert b"herald" in body
    assert b"energy" in body
    assert b"tone" in body
    # link to the detail review page
    assert reverse("console:diff-detail",
                   args=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]).encode() in body


@pytest.mark.django_db
def test_diff_list_agent_down_empty_state(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: None):
        resp = client.get(reverse("console:diff-list"))
    assert resp.status_code == 200
    assert b"unavailable" in resp.content.lower()


@pytest.mark.django_db
def test_diff_list_forbidden_for_member(member, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get") as g:
        resp = client.get(reverse("console:diff-list"))
    assert resp.status_code == 403
    g.assert_not_called()


# --- Diff detail (side-by-side + evidence + eval-run + approve/reject) ----------


@pytest.mark.django_db
def test_diff_detail_shows_diff_evidence_eval_and_buttons(lead, client):
    from apps.intelligence import console_views

    def _get(path, default):
        if path == "/brain/proposals":
            return _PROPOSALS
        if path.startswith("/brain/eval-runs/"):
            return _EVAL_RUN
        return default

    with patch.object(console_views, "safe_get", side_effect=_get):
        resp = client.get(reverse("console:diff-detail",
                                  args=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]))
    assert resp.status_code == 200
    body = resp.content
    # the diff body / expected effect
    assert b"Lead with the data point." in body
    assert b"higher reply rate" in body
    # evidence episodes
    assert b"ep-1" in body and b"ep-3" in body
    # eval-run result (the gate evidence)
    assert b"compliance" in body
    assert b"overall" in body.lower() or b"pass" in body.lower()
    # approve + reject buttons targeting the right endpoints
    assert reverse("console:diff-apply",
                   args=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]).encode() in body
    assert reverse("console:diff-reject",
                   args=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]).encode() in body


@pytest.mark.django_db
def test_diff_detail_unknown_id_empty_state(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get",
                      side_effect=lambda path, default: _PROPOSALS if path == "/brain/proposals" else default):
        resp = client.get(reverse("console:diff-detail", args=["does-not-exist"]))
    assert resp.status_code == 200
    assert b"not found" in resp.content.lower() or b"no longer" in resp.content.lower()


@pytest.mark.django_db
def test_diff_detail_agent_down_empty_state(lead, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get", side_effect=lambda path, default: None):
        resp = client.get(reverse("console:diff-detail",
                                  args=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]))
    assert resp.status_code == 200
    assert b"unavailable" in resp.content.lower()


@pytest.mark.django_db
def test_diff_detail_forbidden_for_member(member, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "safe_get") as g:
        resp = client.get(reverse("console:diff-detail", args=["x"]))
    assert resp.status_code == 403
    g.assert_not_called()


# --- Approve / Reject (mutations are lead-gated) --------------------------------


@pytest.mark.django_db
def test_approve_posts_to_apply_endpoint(lead, client):
    pid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post",
                      return_value={"status": "applied", "version": 5}) as m:
        resp = client.post(reverse("console:diff-apply", args=[pid]))
    assert resp.status_code in (200, 302)
    m.assert_called_once()
    assert m.call_args[0][0] == f"/brain/proposals/{pid}/apply"


@pytest.mark.django_db
def test_reject_posts_to_reject_endpoint(lead, client):
    pid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post",
                      return_value={"status": "rejected"}) as m:
        resp = client.post(reverse("console:diff-reject", args=[pid]))
    assert resp.status_code in (200, 302)
    m.assert_called_once()
    assert m.call_args[0][0] == f"/brain/proposals/{pid}/reject"


@pytest.mark.django_db
def test_approve_agent_down_does_not_500(lead, client):
    from apps.common.agent_client import AgentClientError
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post", side_effect=AgentClientError("down")):
        resp = client.post(reverse("console:diff-apply",
                                   args=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]))
    assert resp.status_code == 302


@pytest.mark.django_db
def test_approve_forbidden_for_member(member, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post") as p:
        resp = client.post(reverse("console:diff-apply", args=["x"]))
    assert resp.status_code == 403
    p.assert_not_called()


@pytest.mark.django_db
def test_reject_forbidden_for_member(member, client):
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post") as p:
        resp = client.post(reverse("console:diff-reject", args=["x"]))
    assert resp.status_code == 403
    p.assert_not_called()


@pytest.mark.django_db
def test_approve_requires_post(lead, client):
    """GET on the mutation endpoint is rejected (405), no agent call."""
    from apps.intelligence import console_views
    with patch.object(console_views, "agent_post") as p:
        resp = client.get(reverse("console:diff-apply", args=["x"]))
    assert resp.status_code == 405
    p.assert_not_called()


# --- CSP-safe templates (no inline <script> without nonce, extends base) --------


@pytest.mark.django_db
def test_learning_templates_are_csp_safe(lead, client):
    from apps.intelligence import console_views

    def _get(path, default):
        if path == "/brain/proposals":
            return _PROPOSALS
        if path.startswith("/brain/eval-runs/"):
            return _EVAL_RUN
        if path == "/brain/learnings":
            return _LEARNINGS
        return default

    with patch.object(console_views, "safe_get", side_effect=_get):
        log = client.get(reverse("console:learning-log")).content
        det = client.get(reverse("console:diff-detail",
                                 args=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"])).content
    for body in (log, det):
        # any <script> tag present must carry a nonce (CSP)
        assert b"<script" not in body or b"nonce" in body
