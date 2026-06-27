"""Render-smoke test for the Calendar / Publish page (Phase C — C1).

Guards the density refactor of ``templates/calendar/calendar.html`` and its
partials: the page must still render 200 in both the default (calendar) mode
and the explicit list mode after the toolbar declutter.
"""
import pytest
from django.urls import reverse

from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_calendar_renders_200(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(
        workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER
    )
    client.force_login(user)
    resp = client.get(
        reverse("calendar:calendar", kwargs={"workspace_id": workspace.id})
    )
    assert resp.status_code == 200


def test_calendar_mode_renders_200(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(
        workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER
    )
    client.force_login(user)
    resp = client.get(
        reverse("calendar:calendar", kwargs={"workspace_id": workspace.id})
        + "?mode=calendar&view=month"
    )
    assert resp.status_code == 200


def test_list_mode_renders_200(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(
        workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER
    )
    client.force_login(user)
    resp = client.get(
        reverse("calendar:calendar", kwargs={"workspace_id": workspace.id})
        + "?mode=list&tab=queue"
    )
    assert resp.status_code == 200
