"""Tests for the TWG → Campaign OS ingest webhook + drafting task."""

import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest

from apps.twg import signing
from apps.twg.models import TwgMeetingEvent

SECRET = "sh4red-t3st-secret"
URL = "/api/ingest/twg-meeting"

PAYLOAD = {
    "meeting_title": "WAIIS-2026 TWG — Strategic Minerals",
    "twg_pillar": "Strategic Minerals",
    "date": "2026-07-02",
    "public_highlights": ["Bullet one", "Bullet two"],
    "public_decisions_milestones": ["Milestone A"],
    "institutions_public": ["Org X"],
    "next_milestone": "Do the thing",
    "minutes_url": "https://twg.example/meetings/abc",
}


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()


# --- signing.verify (pure, security-critical) ---------------------------------


def test_verify_accepts_valid_signature():
    body = b'{"a":1}'
    ts = str(int(time.time()))
    assert signing.verify(body, ts, _sign(SECRET, ts, body), SECRET) is True


def test_verify_rejects_wrong_secret():
    body = b'{"a":1}'
    ts = str(int(time.time()))
    assert signing.verify(body, ts, _sign("other", ts, body), SECRET) is False


def test_verify_rejects_tampered_body():
    ts = str(int(time.time()))
    sig = _sign(SECRET, ts, b'{"a":1}')
    assert signing.verify(b'{"a":2}', ts, sig, SECRET) is False


def test_verify_rejects_stale_timestamp():
    body = b'{"a":1}'
    ts = str(int(time.time()) - 3600)
    assert signing.verify(body, ts, _sign(SECRET, ts, body), SECRET) is False


def test_verify_rejects_bad_timestamp():
    body = b'{"a":1}'
    assert signing.verify(body, "not-a-number", "sha256=x", SECRET) is False


def test_verify_fails_closed_without_secret():
    body = b'{"a":1}'
    ts = str(int(time.time()))
    assert signing.verify(body, ts, _sign("", ts, body), "") is False


# --- webhook ------------------------------------------------------------------


def _post(client, body: bytes, *, secret=SECRET, ts=None, event="minutes.published",
          meeting_id="mtg-1", sign_with=None):
    ts = ts or str(int(time.time()))
    sig = _sign(sign_with if sign_with is not None else secret, ts, body)
    return client.post(
        URL,
        data=body,
        content_type="application/json",
        HTTP_X_WAIIS_EVENT=event,
        HTTP_X_WAIIS_MEETING_ID=meeting_id,
        HTTP_X_WAIIS_TIMESTAMP=ts,
        HTTP_X_WAIIS_SIGNATURE=sig,
    )


@pytest.mark.django_db
def test_webhook_accepts_valid_and_persists_and_enqueues(client, settings):
    settings.TWG_WEBHOOK_SECRET = SECRET
    body = json.dumps(PAYLOAD).encode()
    with patch("apps.twg.tasks.process_twg_meeting") as task:
        resp = _post(client, body, meeting_id="mtg-42")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    ev = TwgMeetingEvent.objects.get(meeting_id="mtg-42")
    assert ev.payload["twg_pillar"] == "Strategic Minerals"
    task.delay.assert_called_once_with(str(ev.id))


@pytest.mark.django_db
def test_webhook_dedupes_on_meeting_id(client, settings):
    settings.TWG_WEBHOOK_SECRET = SECRET
    body = json.dumps(PAYLOAD).encode()
    with patch("apps.twg.tasks.process_twg_meeting") as task:
        first = _post(client, body, meeting_id="dup-1")
        second = _post(client, body, meeting_id="dup-1")
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"
    assert TwgMeetingEvent.objects.filter(meeting_id="dup-1").count() == 1
    assert task.delay.call_count == 1  # only the first enqueues


@pytest.mark.django_db
def test_webhook_rejects_bad_signature(client, settings):
    settings.TWG_WEBHOOK_SECRET = SECRET
    body = json.dumps(PAYLOAD).encode()
    resp = _post(client, body, sign_with="wrong-secret")
    assert resp.status_code == 403
    assert TwgMeetingEvent.objects.count() == 0


@pytest.mark.django_db
def test_webhook_rejects_unknown_event(client, settings):
    settings.TWG_WEBHOOK_SECRET = SECRET
    body = json.dumps(PAYLOAD).encode()
    resp = _post(client, body, event="something.else")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_webhook_rejects_missing_meeting_id(client, settings):
    settings.TWG_WEBHOOK_SECRET = SECRET
    body = json.dumps(PAYLOAD).encode()
    resp = _post(client, body, meeting_id="")
    assert resp.status_code == 400


# --- drafting task ------------------------------------------------------------


def _accounts(workspace, platforms):
    from apps.social_accounts.models import SocialAccount

    for i, platform in enumerate(platforms):
        SocialAccount.objects.create(
            workspace=workspace, platform=platform, account_platform_id=f"acct-{i}",
            account_name=f"{platform} acct",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )


@pytest.mark.django_db
def test_task_publish_decision_creates_posts_and_schedules(workspace, settings):
    settings.TWG_INGEST_WORKSPACE_ID = str(workspace.id)
    _accounts(workspace, ["blotato_linkedin", "blotato_twitter", "ghost"])

    plan = {
        "decision": "publish",
        "reason": "confirmed milestone",
        "posts": [
            {"platform": "linkedin", "caption": "LI recap [NEXUS BRIEF LINK]", "hashtags": ["WAIIS2026"]},
            {"platform": "ghost", "caption": "Full brief body"},
        ],
        "excluded": [],
    }
    event = TwgMeetingEvent.objects.create(meeting_id="mtg-pub", payload=PAYLOAD)
    with patch("apps.twg.herald.curate", return_value=plan), \
         patch("apps.composer.views.schedule_now") as sched:
        from apps.twg.tasks import process_twg_meeting
        result = process_twg_meeting(str(event.id))

    event.refresh_from_db()
    assert result.startswith("publish:")
    assert event.status == TwgMeetingEvent.Status.DRAFTED
    pps = {pp.social_account.platform: pp for pp in event.post.platform_posts.all()}
    assert set(pps) == {"blotato_linkedin", "ghost"}
    assert "#WAIIS2026" in pps["blotato_linkedin"].platform_specific_caption  # hashtags appended
    assert "#" not in pps["ghost"].platform_specific_caption  # ghost long-form, no hashtags
    sched.assert_called_once()


@pytest.mark.django_db
def test_task_hold_decision_emails_joseph(workspace, settings):
    settings.TWG_INGEST_WORKSPACE_ID = str(workspace.id)
    settings.JOSEPH_APPROVER_EMAIL = "joseph@africacen.org"
    _accounts(workspace, ["blotato_linkedin"])
    plan = {"decision": "hold", "reason": "ambiguous", "posts": [{"platform": "linkedin", "caption": "x"}], "excluded": []}
    event = TwgMeetingEvent.objects.create(meeting_id="mtg-hold", payload=PAYLOAD)
    with patch("apps.twg.herald.curate", return_value=plan), \
         patch("apps.approvals.assignment_service.assign_for_review") as assign:
        from apps.twg.tasks import process_twg_meeting
        result = process_twg_meeting(str(event.id))
    event.refresh_from_db()
    assert result.startswith("hold:")
    assert event.status == TwgMeetingEvent.Status.DRAFTED
    assign.assert_called_once()
    assert assign.call_args.kwargs["reviewer_email"] == "joseph@africacen.org"


@pytest.mark.django_db
def test_task_none_decision_skips(workspace, settings):
    settings.TWG_INGEST_WORKSPACE_ID = str(workspace.id)
    _accounts(workspace, ["blotato_linkedin"])
    plan = {"decision": "none", "reason": "nothing post-worthy", "posts": [], "excluded": []}
    event = TwgMeetingEvent.objects.create(meeting_id="mtg-none", payload=PAYLOAD)
    with patch("apps.twg.herald.curate", return_value=plan):
        from apps.twg.tasks import process_twg_meeting
        result = process_twg_meeting(str(event.id))
    event.refresh_from_db()
    assert result == "none"
    assert event.status == TwgMeetingEvent.Status.SKIPPED
    assert event.post is None


# --- HERALD curation (fail-safe) ---------------------------------------------


@pytest.mark.django_db
def test_curate_parses_json_response(settings):
    from apps.twg import herald
    resp = '```json\n{"decision":"publish","reason":"ok","posts":[{"platform":"linkedin","caption":"c"}]}\n```'
    with patch("apps.twg.herald.deepseek_client.deepseek_available", return_value=True), \
         patch("apps.twg.herald.deepseek_client.chat", return_value=resp):
        out = herald.curate({"twg_pillar": "Agribusiness"}, ["linkedin"])
    assert out["decision"] == "publish"
    assert out["posts"][0]["platform"] == "linkedin"


@pytest.mark.django_db
def test_curate_failsafe_holds_on_bad_output(settings):
    from apps.twg import herald
    with patch("apps.twg.herald.deepseek_client.deepseek_available", return_value=True), \
         patch("apps.twg.herald.deepseek_client.chat", return_value="sorry, no JSON here"):
        out = herald.curate({"twg_pillar": "Energy"}, ["linkedin"])
    assert out["decision"] == "hold"
    assert out["posts"] == []


@pytest.mark.django_db
def test_curate_failsafe_when_engine_unavailable():
    from apps.twg import herald
    with patch("apps.twg.herald.deepseek_client.deepseek_available", return_value=False):
        out = herald.curate({"twg_pillar": "Energy"}, ["linkedin"])
    assert out["decision"] == "hold"


@pytest.mark.django_db
def test_task_fails_cleanly_without_workspace(settings):
    settings.TWG_INGEST_WORKSPACE_ID = ""
    event = TwgMeetingEvent.objects.create(meeting_id="mtg-nows", payload=PAYLOAD)
    from apps.twg.tasks import process_twg_meeting

    result = process_twg_meeting(str(event.id))
    event.refresh_from_db()
    assert event.status == TwgMeetingEvent.Status.FAILED
    assert result.startswith("failed:")
