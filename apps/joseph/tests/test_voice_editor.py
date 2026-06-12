from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.fixture
def joseph(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    return org_owner


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
