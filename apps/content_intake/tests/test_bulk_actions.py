# apps/content_intake/tests/test_bulk_actions.py
import pytest
from unittest.mock import patch
from django.urls import reverse
from apps.content_intake.models import ContentIntake


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_draft_selected_drafts_each_eligible(authed, workspace):
    a = ContentIntake.objects.create(workspace=workspace, external_id="A", angle="a",
        sensitivity="public_safe", status="accepted")
    b = ContentIntake.objects.create(workspace=workspace, external_id="B", angle="b",
        sensitivity="public_safe", status="accepted")
    url = reverse("console:intake-draft-selected")
    with patch("apps.content_intake.views.request_herald_draft", return_value=True) as m:
        resp = authed.post(url, {"ids": [str(a.pk), str(b.pk)]})
    assert resp.status_code == 200
    assert m.call_count == 2


@pytest.mark.django_db
def test_draft_selected_no_per_item_condition_probe(authed, workspace):
    """The bulk-draft queryset annotates ``open_cond_count`` so the per-item
    request_herald_draft -> _is_eligible -> is_schedulable -> has_open_conditions
    check reads the annotation instead of firing one targeted EXISTS query per
    selected item.

    Unlike test_draft_selected_drafts_each_eligible (which fully mocks
    request_herald_draft and therefore never exercises the eligibility DB path),
    this test patches only the agent HTTP call (agent_post). That leaves the real
    eligibility logic — including the open-condition lookup — running against the
    database, which is where the N+1 lives. Mirrors
    test_add_to_calendar_no_per_item_condition_probe: assert on the per-item
    EXISTS probe signature (not a raw query-count budget) so the test stays
    meaningful even though the trailing board() re-render legitimately issues its
    own batched annotate+prefetch."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    items = [
        ContentIntake.objects.create(
            workspace=workspace, external_id=f"DS-N{i}", angle="a",
            sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
            status=ContentIntake.Status.ACCEPTED,
        )
        for i in range(5)
    ]
    url = reverse("console:intake-draft-selected")
    ids = [str(i.pk) for i in items]

    # Patch the HTTP boundary, not the bridge itself, so _is_eligible (and thus
    # is_schedulable / has_open_conditions) runs against the real DB.
    with patch(
        "apps.content_intake.herald_bridge.agent_post",
        return_value={"proposals": [{"content_id": "c1"}]},
    ):
        with CaptureQueriesContext(connection) as ctx:
            resp = authed.post(url, {"ids": ids})

    assert resp.status_code == 200
    for item in items:
        item.refresh_from_db()
        assert item.status == ContentIntake.Status.DRAFTING

    # The per-item open-condition EXISTS probe: SELECT 1 ... status = 'open' LIMIT 1.
    # With the annotation in place this must be issued zero times; without it,
    # has_open_conditions would emit one such probe per item (here, 5).
    probes = [
        q["sql"] for q in ctx.captured_queries
        if "unblock_condition" in q["sql"].lower()
        and "= 'open'" in q["sql"].lower()
        and "limit 1" in q["sql"].lower()
    ]
    assert probes == [], (
        f"expected 0 per-item open-condition EXISTS probes (annotation should be "
        f"used), saw {len(probes)}: {probes}"
    )

    # And every condition query that does run is a batched lookup (annotation JOIN
    # or prefetch IN-list), never a per-item probe — so the cost is O(1) in items.
    cond_queries = [
        q["sql"] for q in ctx.captured_queries
        if "unblock_condition" in q["sql"].lower()
    ]
    for sql in cond_queries:
        assert "limit 1" not in sql.lower(), f"unexpected per-item probe: {sql}"
