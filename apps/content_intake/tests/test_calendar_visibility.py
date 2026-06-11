from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.composer.models import Post


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_channelless_scheduled_post_shows_on_calendar(authed, workspace):
    when = timezone.now() + timedelta(days=1)
    post = Post.objects.create(workspace=workspace, title="Planning item",
                               caption="x", scheduled_at=when)
    # No PlatformPost — channel-less.
    url = (
        reverse("calendar:calendar", args=[workspace.pk])
        + f"?mode=calendar&view=month&date={when.date().isoformat()}"
    )
    resp = authed.get(url)
    assert resp.status_code == 200
    assert b"Planning item" in resp.content
