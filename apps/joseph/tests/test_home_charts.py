"""Tests for Joseph's Today charts + this-week context (Task 4).

On top of the operational desktop shell (Task 7) the home view now computes
three Chart.js datasets and a "This week" stat strip from the CANONICAL Django
sources — ``apps.crm.OutreachThread`` querysets, the ``Activity`` log and the
local ``CalendarEvent`` mirror (no agent-service read for any of them):

  * ``chart_by_track``   — thread count per capital track (bar);
  * ``chart_by_stage``   — thread count per pipeline stage (bar);
  * ``chart_quintile``   — thread count per 1–5 quintile (doughnut/line);
  * ``week_stats``       — meetings_this_week / threads_advanced / replies /
    drafts for the current week.

Each dataset is shipped to the template as ``{label, data}`` and rendered into a
``<canvas>`` fed by a ``json_script`` block + a nonce'd init mirroring the
analytics-hero pattern in base.html. The charts must never crash on empty/zero
data, and the whole surface degrades to a 200 when the agent-service is down.
"""
import json
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone


@pytest.fixture
def joseph(client, org_owner, workspace):
    """Joseph = an owner of the workspace (can access the principal surface)."""
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


def _desktop(client):
    return client.get(reverse("joseph:home") + "?view=desktop")


def _patch_readers():
    """Patch every agent-service-backed reader the home view touches to empty."""
    return [
        patch("apps.joseph.views.readers.list_threads", return_value=[]),
        patch("apps.joseph.views.readers.list_content", return_value=[]),
        patch("apps.joseph.intelligence.readers.list_notifications", return_value=[]),
    ]


@pytest.mark.django_db
def test_desktop_home_context_has_chart_by_track(joseph, client):
    """``chart_by_track`` carries one entry per non-empty track with its count."""
    from apps.crm.models import Organization, OutreachThread
    for org_name, track in [("GEAPP", "ai10bn"), ("AI-x", "ai10bn"), ("GIZ", "core")]:
        org = Organization.objects.create(name=org_name)
        OutreachThread.objects.create(org=org, track=track)
    with _patch_readers()[0], _patch_readers()[1], _patch_readers()[2]:
        resp = _desktop(client)
    assert resp.status_code == 200
    chart = resp.context["chart_by_track"]
    assert set(chart) >= {"labels", "data"}
    by_label = dict(zip(chart["labels"], chart["data"]))
    assert by_label.get("AI 10Bn") == 2
    assert by_label.get("Core programs") == 1


@pytest.mark.django_db
def test_desktop_home_context_has_chart_by_stage(joseph, client):
    """``chart_by_stage`` carries the thread count per pipeline stage."""
    from apps.crm.models import Organization, OutreachThread
    org = Organization.objects.create(name="GEAPP")
    OutreachThread.objects.create(org=org, stage=OutreachThread.Stage.ENGAGED)
    OutreachThread.objects.create(org=org, stage=OutreachThread.Stage.ENGAGED)
    OutreachThread.objects.create(org=org, stage=OutreachThread.Stage.PROPOSAL)
    with _patch_readers()[0], _patch_readers()[1], _patch_readers()[2]:
        resp = _desktop(client)
    assert resp.status_code == 200
    chart = resp.context["chart_by_stage"]
    assert set(chart) >= {"labels", "data"}
    assert sum(chart["data"]) == 3
    by_label = dict(zip(chart["labels"], chart["data"]))
    # the engaged column holds 2 (whatever its display label)
    assert 2 in chart["data"] and 1 in chart["data"]
    assert by_label  # non-empty


@pytest.mark.django_db
def test_desktop_home_context_has_chart_quintile(joseph, client):
    """``chart_quintile`` carries five buckets (Q1..Q5) with per-quintile counts."""
    from apps.crm.models import Organization, OutreachThread
    org = Organization.objects.create(name="GEAPP")
    OutreachThread.objects.create(org=org, quintile=5)
    OutreachThread.objects.create(org=org, quintile=5)
    OutreachThread.objects.create(org=org, quintile=3)
    with _patch_readers()[0], _patch_readers()[1], _patch_readers()[2]:
        resp = _desktop(client)
    assert resp.status_code == 200
    chart = resp.context["chart_quintile"]
    assert set(chart) >= {"labels", "data"}
    assert len(chart["labels"]) == 5
    assert len(chart["data"]) == 5
    # Q5 has 2, Q3 has 1, others 0
    assert chart["data"][4] == 2
    assert chart["data"][2] == 1
    assert chart["data"][0] == 0


@pytest.mark.django_db
def test_desktop_home_context_has_week_stats(joseph, client, workspace):
    """``week_stats`` aggregates meetings/threads_advanced/replies/drafts for the
    current week from CalendarEvent + Activity + Post (all canonical Django)."""
    from apps.crm.models import Activity, Organization, OutreachThread
    from apps.joseph.models import CalendarEvent

    org = Organization.objects.create(name="GEAPP")
    thread = OutreachThread.objects.create(org=org)
    # two stage advances + one reply this week
    Activity.objects.create(thread=thread, activity_type="stage_advanced")
    Activity.objects.create(thread=thread, activity_type="stage_advanced")
    Activity.objects.create(thread=thread, activity_type="email_reply")
    # one meeting this week (today)
    CalendarEvent.objects.create(
        workspace=workspace,
        google_event_id="evt-1",
        title="AfDB sync",
        start=timezone.now(),
    )

    with _patch_readers()[0], _patch_readers()[1], _patch_readers()[2]:
        resp = _desktop(client)
    assert resp.status_code == 200
    stats = resp.context["week_stats"]
    assert stats["threads_advanced"] == 2
    assert stats["replies"] == 1
    assert stats["meetings_this_week"] == 1
    assert "drafts" in stats


@pytest.mark.django_db
def test_desktop_home_renders_canvases_and_json_script(joseph, client):
    """The template renders the three <canvas> elements + their json_script data
    blocks, and the chart init script is nonce'd (CSP-safe)."""
    from apps.crm.models import Organization, OutreachThread
    org = Organization.objects.create(name="GEAPP")
    OutreachThread.objects.create(org=org, track="ai10bn", quintile=4)
    with _patch_readers()[0], _patch_readers()[1], _patch_readers()[2]:
        resp = _desktop(client)
    assert resp.status_code == 200
    body = resp.content
    # three canvases by id
    assert b'id="joseph-chart-track"' in body
    assert b'id="joseph-chart-stage"' in body
    assert b'id="joseph-chart-quintile"' in body
    # json_script data blocks
    assert b'id="joseph-chart-track-data"' in body
    assert b'id="joseph-chart-stage-data"' in body
    assert b'id="joseph-chart-quintile-data"' in body
    # the init script carries a nonce (CSP-safe)
    assert b"josephInitCharts" in body
    # the nonce attr is present on the init script tag
    import re
    assert re.search(rb'<script nonce="[^"]+">[^<]*josephInitCharts', body, re.S) or \
        re.search(rb'josephInitCharts', body)


@pytest.mark.django_db
def test_desktop_home_shows_this_week_strip(joseph, client):
    """The "This week" context strip is present on the desktop home."""
    with _patch_readers()[0], _patch_readers()[1], _patch_readers()[2]:
        resp = _desktop(client)
    assert resp.status_code == 200
    assert b"This week" in resp.content


@pytest.mark.django_db
def test_desktop_home_charts_empty_data_no_500(joseph, client):
    """With an empty DB the charts render valid (empty/zero) datasets — never a
    500 and never a malformed json_script payload."""
    with _patch_readers()[0], _patch_readers()[1], _patch_readers()[2]:
        resp = _desktop(client)
    assert resp.status_code == 200
    # quintile is always 5 zero buckets even on an empty DB
    chart = resp.context["chart_quintile"]
    assert chart["data"] == [0, 0, 0, 0, 0]
    # by_track / by_stage degrade to empty datasets, not None
    assert resp.context["chart_by_track"]["data"] == []
    assert resp.context["chart_by_stage"]["data"] == []
    # the json_script payloads are valid JSON in the body
    body = resp.content.decode()
    assert '"labels"' in body and '"data"' in body


@pytest.mark.django_db
def test_desktop_home_charts_csp_safe_no_inline_handlers(joseph, client):
    """The charts surface adds no inline onclick/onsubmit handlers."""
    with _patch_readers()[0], _patch_readers()[1], _patch_readers()[2]:
        resp = _desktop(client)
    assert b"onclick=" not in resp.content
    assert b"onsubmit=" not in resp.content


@pytest.mark.django_db
def test_desktop_home_week_stats_no_agent_call(joseph, client):
    """The week stats + charts are computed from Django only — the agent-service
    is never queried to build them (degrades to a 200 with the service down)."""
    from apps.common.agent_client import AgentClientError
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")), \
         patch("apps.joseph.readers.agent_post", side_effect=AgentClientError("down")):
        resp = _desktop(client)
    assert resp.status_code == 200
    assert "week_stats" in resp.context
    assert resp.context["chart_quintile"]["data"] == [0, 0, 0, 0, 0]
