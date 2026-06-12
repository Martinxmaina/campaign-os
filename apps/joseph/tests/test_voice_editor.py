from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.fixture
def joseph(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    return org_owner


@pytest.fixture
def member(client, db, organization, workspace):
    """An ordinary (non-admin) workspace member — must not manage the brand voice.

    A post_save signal auto-provisions every new user as OWNER of the AfCEN/WAIIS
    singleton org+workspace, so we first strip those auto-granted memberships,
    then grant a genuine ``member`` role in the test workspace and point
    ``last_workspace_id`` there so RBACMiddleware resolves the member membership.
    """
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership
    u = User.objects.create_user(
        email="member@example.com", password="x", name="Member", tos_accepted_at=timezone.now())
    # Strip the singleton-owner memberships the signup signal auto-granted.
    WorkspaceMembership.objects.filter(user=u).delete()
    OrgMembership.objects.filter(user=u).delete()
    OrgMembership.objects.create(user=u, organization=organization, org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=u, workspace=workspace, workspace_role="member")
    u.last_workspace_id = workspace.id
    u.save(update_fields=["last_workspace_id"])
    client.force_login(u)
    return u


@pytest.mark.django_db
def test_voice_editor_renders_sections(joseph, client):
    fake = {"user": "joseph", "body": {"tone": "Direct and data-led", "banned_phrases": ["leverage"],
            "openers": "x", "signature_moves": [], "hooks_by_audience": {}, "length_by_channel": {}}}
    with patch("apps.joseph.views.agent_get", return_value=fake):
        resp = client.get(reverse("joseph:voice"))
    assert resp.status_code == 200
    assert b"Direct and data-led" in resp.content
    assert b"leverage" in resp.content


@pytest.mark.django_db
def test_voice_save_puts_new_version(joseph, client):
    with patch("apps.joseph.views.agent_put", return_value={"version": 2}) as m:
        resp = client.post(reverse("joseph:voice-save"), {
            "tone": "t", "openers": "o", "banned_phrases": "leverage, synergies",
            "signature_moves": "SE4ALL precedent", "length_by_channel_linkedin": "250-400",
        })
    assert resp.status_code in (200, 302)
    m.assert_called_once()
    # banned_phrases sent as a list
    sent = m.call_args[0][1]
    assert "leverage" in sent["body"]["banned_phrases"]


@pytest.mark.django_db
def test_voice_editor_renders_pending_proposal(joseph, client):
    fake = {"user": "joseph", "body": {"tone": "t", "banned_phrases": [], "openers": "",
            "signature_moves": [], "hooks_by_audience": {}, "length_by_channel": {}}}
    proposals = {"proposals": [{"id": 7, "proposed_body": {"tone": "Sharper and data-led"},
                                "rationale": "weekly reflect"}]}

    def _get(path):
        return proposals if path.endswith("/proposals") else fake

    with patch("apps.joseph.views.agent_get", side_effect=_get):
        resp = client.get(reverse("joseph:voice"))
    assert resp.status_code == 200
    assert b"Pending proposal #7" in resp.content
    assert reverse("joseph:voice-apply-proposal", args=[7]).encode() in resp.content


@pytest.mark.django_db
def test_voice_apply_proposal_calls_agent(joseph, client):
    with patch("apps.joseph.views.agent_post", return_value={"version": 3}) as m:
        resp = client.post(reverse("joseph:voice-apply-proposal", args=[7]))
    assert resp.status_code in (200, 302)
    m.assert_called_once()
    assert "/voice/joseph/proposals/7/apply" in m.call_args[0][0]


@pytest.mark.django_db
def test_voice_apply_proposal_routes_uuid_id(joseph, client):
    """agent-service VoiceProposal.id is a UUID string; the apply/dismiss URLs must
    reverse and route UUID ids end-to-end (an <int:> converter would 404 in prod)."""
    pid = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    apply_url = reverse("joseph:voice-apply-proposal", args=[pid])
    assert pid in apply_url
    with patch("apps.joseph.views.agent_post", return_value={"version": 3}) as m:
        resp = client.post(apply_url)
    assert resp.status_code in (200, 302)
    assert f"/voice/joseph/proposals/{pid}/apply" in m.call_args[0][0]


@pytest.mark.django_db
def test_voice_dismiss_proposal_routes_uuid_id(joseph, client):
    pid = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    dismiss_url = reverse("joseph:voice-dismiss-proposal", args=[pid])
    assert pid in dismiss_url
    with patch("apps.joseph.views.agent_post", return_value={"status": "dismissed"}) as m:
        resp = client.post(dismiss_url)
    assert resp.status_code in (200, 302)
    assert f"/voice/joseph/proposals/{pid}/dismiss" in m.call_args[0][0]


# --- Authorization: the voice profile is a global, org-wide brand-voice config.
# Mere authentication is not enough — only owner/admin (or staff) may read/mutate it. ---


@pytest.mark.django_db
def test_voice_editor_forbidden_for_non_admin_member(member, client):
    """A non-admin member can authenticate but must not read the brand voice,
    and the agent-service must not be hit at all."""
    with patch("apps.joseph.views.agent_get") as g:
        resp = client.get(reverse("joseph:voice"))
    assert resp.status_code == 403
    g.assert_not_called()


@pytest.mark.django_db
def test_voice_save_forbidden_for_non_admin_member(member, client):
    """A non-admin member must not be able to overwrite the brand voice."""
    with patch("apps.joseph.views.agent_put") as put, patch("apps.joseph.views.agent_get") as g:
        resp = client.post(reverse("joseph:voice-save"), {"tone": "hijacked"})
    assert resp.status_code == 403
    put.assert_not_called()
    g.assert_not_called()


@pytest.mark.django_db
def test_voice_apply_proposal_forbidden_for_non_admin_member(member, client):
    with patch("apps.joseph.views.agent_post") as p:
        resp = client.post(reverse("joseph:voice-apply-proposal", args=[7]))
    assert resp.status_code == 403
    p.assert_not_called()


@pytest.mark.django_db
def test_voice_dismiss_proposal_forbidden_for_non_admin_member(member, client):
    with patch("apps.joseph.views.agent_post") as p:
        resp = client.post(reverse("joseph:voice-dismiss-proposal", args=[7]))
    assert resp.status_code == 403
    p.assert_not_called()


@pytest.mark.django_db
def test_voice_editor_allowed_for_staff(client, db):
    """Staff (superuser escape hatch) may manage the brand voice even without an
    owner/admin workspace membership."""
    from django.utils import timezone
    from apps.accounts.models import User
    staff = User.objects.create_user(
        email="staff@example.com", password="x", name="Staff",
        tos_accepted_at=timezone.now(), is_staff=True)
    client.force_login(staff)
    fake = {"body": {"tone": "t", "banned_phrases": [], "openers": "",
            "signature_moves": [], "hooks_by_audience": {}, "length_by_channel": {}}}
    with patch("apps.joseph.views.agent_get", return_value=fake):
        resp = client.get(reverse("joseph:voice"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_voice_save_handles_agent_down_gracefully(joseph, client):
    """A down/unconfigured agent-service on the PUT must not 500 — it should
    redirect with an error message, matching the apply/dismiss views."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.views.agent_get", return_value={"body": {}}), \
         patch("apps.joseph.views.agent_put", side_effect=AgentClientError("down")):
        resp = client.post(reverse("joseph:voice-save"), {"tone": "t"})
    assert resp.status_code == 302
