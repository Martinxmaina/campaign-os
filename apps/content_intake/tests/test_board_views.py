import pytest
from django.urls import reverse
from apps.content_intake.models import ContentIntake


@pytest.fixture
def authed(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    # RBACMiddleware resolves request.workspace for non-workspace_id URLs (the
    # intake board uses /intake/<intake_pk>/...) via user.last_workspace_id, so
    # point it at this workspace. The accounts post_save signal seeds a separate
    # singleton workspace on user creation, so we must overwrite it explicitly
    # for the membership above to take effect.
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return client


@pytest.mark.django_db
def test_row_panel_renders_doc_chips(authed, workspace):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="P-1", pillar_theme="Energy", angle="Solar",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
        reference_links=[{"title": "Brief", "url": "https://docs.google.com/document/d/z/edit", "type": "gdoc"}],
    )
    url = reverse("console:intake-row-panel", args=[item.pk])
    resp = authed.get(url)
    assert resp.status_code == 200
    assert b"Brief" in resp.content
    assert b"docs.google.com/document/d/z" in resp.content


@pytest.mark.django_db
def test_board_sorts_by_param(authed, workspace):
    ContentIntake.objects.create(workspace=workspace, external_id="A", pillar_theme="Zeta",
        sensitivity="public_safe", status="idea")
    ContentIntake.objects.create(workspace=workspace, external_id="B", pillar_theme="Alpha",
        sensitivity="public_safe", status="idea")
    url = reverse("console:intake-board") + "?sort=pillar"
    resp = authed.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert body.index("Alpha") < body.index("Zeta")


@pytest.mark.django_db
def test_board_partial_returns_table_only(authed, workspace):
    ContentIntake.objects.create(workspace=workspace, external_id="A", pillar_theme="Energy",
        sensitivity="public_safe", status="idea")
    url = reverse("console:intake-board") + "?partial=1"
    resp = authed.get(url)
    assert resp.status_code == 200
    # Partial must NOT include the full page chrome (no <h1>Content Intake Board</h1>)
    assert b"intake-table" in resp.content
    assert b"Content Intake Board" not in resp.content


@pytest.mark.django_db
def test_sort_header_preserves_filters(authed, workspace):
    """Column-header sort links must carry the active status/pillar filters so a
    sort click does not silently reset them."""
    ContentIntake.objects.create(workspace=workspace, external_id="A", pillar_theme="Energy",
        sensitivity="public_safe", status="idea")
    url = reverse("console:intake-board") + "?status=idea&pillar=Energy"
    resp = authed.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # The pillar-sort header must round-trip both active filters.
    assert "?sort=pillar&status=idea&pillar=Energy" in body


@pytest.mark.django_db
def test_draft_now_panel_hx_success_rerenders_panel(authed, workspace):
    """Panel HX success re-renders _panel.html (preserving #intake-panel), not a
    card fragment, so subsequent row clicks still have a swap target."""
    from unittest.mock import patch

    item = ContentIntake.objects.create(workspace=workspace, external_id="P-1",
        pillar_theme="Energy", angle="Solar", sensitivity="public_safe", status="accepted")
    url = reverse("console:intake-draft-now-panel", args=[item.pk])

    def _fake_draft(obj):
        obj.status = ContentIntake.Status.DRAFTING
        obj.save(update_fields=["status"])
        return True

    with patch("apps.content_intake.views.request_herald_draft", side_effect=_fake_draft):
        resp = authed.post(url, HTTP_HX_REQUEST="true")

    assert resp.status_code == 200
    # The panel id is preserved (so row clicks keep their #intake-panel target)...
    assert b'id="intake-panel"' in resp.content
    # ...and no stray card fragment id is emitted.
    assert f"intake-card-{item.pk}".encode() not in resp.content


@pytest.mark.django_db
def test_draft_now_panel_hx_failure_retargets_panel(authed, workspace):
    """Panel HX failure surfaces the error banner and retargets #intake-panel (not
    a nonexistent #intake-card-{pk}), so the banner is not silently dropped."""
    from unittest.mock import patch

    item = ContentIntake.objects.create(workspace=workspace, external_id="P-2",
        pillar_theme="Energy", angle="Solar", sensitivity="public_safe", status="accepted")
    url = reverse("console:intake-draft-now-panel", args=[item.pk])

    with patch("apps.content_intake.views.request_herald_draft", return_value=False):
        resp = authed.post(url, HTTP_HX_REQUEST="true")

    assert resp.status_code == 200
    assert b"HERALD couldn't draft" in resp.content
    assert resp["HX-Retarget"] == "#intake-panel"
    assert resp["HX-Reswap"] == "afterbegin"


@pytest.mark.django_db
def test_sync_now_triggers_sync_and_returns_table(authed, workspace):
    from unittest.mock import patch
    url = reverse("console:intake-sync-now")
    with patch("apps.content_intake.views.sync_sheet_to_intake", return_value={"created": 0}) as m:
        resp = authed.post(url)
    assert resp.status_code == 200
    assert b"intake-table" in resp.content
    m.assert_called_once()


# ---------------------------------------------------------------------------
# add_to_calendar — the most logic-dense new path: multi-id loop, scheduled_at
# ISO parsing, ValueError fallback, make_aware coercion, partial render.
# ---------------------------------------------------------------------------


def _accepted(workspace, external_id):
    return ContentIntake.objects.create(
        workspace=workspace, external_id=external_id, pillar_theme="Energy",
        angle="Solar", sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )


@pytest.mark.django_db
def test_add_to_calendar_schedules_multiple_items_with_iso_time(authed, workspace):
    """A multi-id POST with an explicit (tz-aware) ISO scheduled_at schedules every
    selected item to that instant and returns the table partial."""
    from datetime import datetime, timezone as _tz

    a = _accepted(workspace, "CAL-A")
    b = _accepted(workspace, "CAL-B")
    url = reverse("console:intake-add-to-calendar")

    resp = authed.post(url, {
        "ids": [str(a.pk), str(b.pk)],
        "scheduled_at": "2026-07-01T09:00:00+00:00",
    })

    assert resp.status_code == 200
    assert b"intake-table" in resp.content
    want = datetime(2026, 7, 1, 9, 0, tzinfo=_tz.utc)
    for item in (a, b):
        item.refresh_from_db()
        assert item.status == ContentIntake.Status.SCHEDULED
        assert item.post_id is not None
        assert item.post.scheduled_at == want


@pytest.mark.django_db
def test_add_to_calendar_make_aware_coerces_naive_iso(authed, workspace):
    """A naive ISO scheduled_at (no offset) is coerced to an aware datetime via
    make_aware rather than crashing or being stored naive."""
    from django.utils import timezone as _tz

    a = _accepted(workspace, "CAL-NAIVE")
    url = reverse("console:intake-add-to-calendar")

    resp = authed.post(url, {"ids": [str(a.pk)], "scheduled_at": "2026-07-01T09:00:00"})

    assert resp.status_code == 200
    a.refresh_from_db()
    assert a.post_id is not None
    assert _tz.is_aware(a.post.scheduled_at)
    assert a.post.scheduled_at.year == 2026 and a.post.scheduled_at.month == 7


@pytest.mark.django_db
def test_add_to_calendar_invalid_scheduled_at_falls_back_to_now(authed, workspace):
    """A malformed scheduled_at hits the ValueError branch and falls back to
    timezone.now() instead of raising a 500."""
    from django.utils import timezone as _tz

    a = _accepted(workspace, "CAL-BAD")
    url = reverse("console:intake-add-to-calendar")
    before = _tz.now()

    resp = authed.post(url, {"ids": [str(a.pk)], "scheduled_at": "not-a-date"})

    after = _tz.now()
    assert resp.status_code == 200
    a.refresh_from_db()
    assert a.status == ContentIntake.Status.SCHEDULED
    assert before <= a.post.scheduled_at <= after


@pytest.mark.django_db
def test_add_to_calendar_missing_scheduled_at_falls_back_to_now(authed, workspace):
    """An omitted scheduled_at also falls back to timezone.now()."""
    from django.utils import timezone as _tz

    a = _accepted(workspace, "CAL-NONE")
    url = reverse("console:intake-add-to-calendar")
    before = _tz.now()

    resp = authed.post(url, {"ids": [str(a.pk)]})

    after = _tz.now()
    assert resp.status_code == 200
    a.refresh_from_db()
    assert a.status == ContentIntake.Status.SCHEDULED
    assert before <= a.post.scheduled_at <= after


@pytest.mark.django_db
def test_add_to_calendar_skips_blocked_item(authed, workspace):
    """An item with an open unblock condition is not schedulable and is skipped,
    while a schedulable sibling in the same POST is still scheduled."""
    from apps.content_intake.models import UnblockCondition

    ok = _accepted(workspace, "CAL-OK")
    blocked = _accepted(workspace, "CAL-BLOCKED")
    UnblockCondition.objects.create(intake=blocked, condition_type="legal_milestone",
        description="MoU pending", status="open")
    url = reverse("console:intake-add-to-calendar")

    resp = authed.post(url, {"ids": [str(ok.pk), str(blocked.pk)]})

    assert resp.status_code == 200
    ok.refresh_from_db()
    blocked.refresh_from_db()
    assert ok.status == ContentIntake.Status.SCHEDULED and ok.post_id is not None
    assert blocked.post_id is None
    assert blocked.status == ContentIntake.Status.ACCEPTED


@pytest.mark.django_db
def test_add_to_calendar_does_not_cross_workspace(authed, workspace):
    """Items in another workspace are excluded by the queryset filter even if their
    ids are submitted, enforcing the cross-house wall."""
    from apps.workspaces.models import Workspace

    other_ws = Workspace.objects.create(organization=workspace.organization, name="Other House")
    foreign = _accepted(other_ws, "CAL-FOREIGN")
    url = reverse("console:intake-add-to-calendar")

    resp = authed.post(url, {"ids": [str(foreign.pk)]})

    assert resp.status_code == 200
    foreign.refresh_from_db()
    assert foreign.post_id is None
    assert foreign.status == ContentIntake.Status.ACCEPTED


@pytest.mark.django_db
def test_add_to_calendar_no_per_item_condition_probe(authed, workspace):
    """The bulk-schedule queryset annotates ``open_cond_count`` so the per-item
    is_schedulable -> has_open_conditions check reads the annotation instead of
    firing one targeted EXISTS query per selected item.

    The N+1 anti-pattern has a distinctive signature: a `SELECT 1 ... WHERE
    intake_id = <pk> AND status = 'open' LIMIT 1` probe issued once per item, so
    the count scales with the number of items scheduled. Annotate+prefetch
    collapses all open-condition lookups into batched queries, so that per-item
    probe must not appear at all. We assert on the probe signature (not a raw
    query-count budget) so the test stays meaningful even though the trailing
    board() re-render legitimately issues its own batched annotate+prefetch."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    items = [_accepted(workspace, f"CAL-N{i}") for i in range(5)]
    url = reverse("console:intake-add-to-calendar")
    ids = [str(i.pk) for i in items]

    with CaptureQueriesContext(connection) as ctx:
        resp = authed.post(url, {"ids": ids})

    assert resp.status_code == 200
    for item in items:
        item.refresh_from_db()
        assert item.status == ContentIntake.Status.SCHEDULED

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


@pytest.mark.django_db
def test_board_kanban_view_groups_by_stage(authed, workspace):
    from apps.content_intake.models import ContentIntake
    ContentIntake.objects.create(workspace=workspace, external_id="K1", pillar_theme="Energy",
        sensitivity="public_safe", status="idea")          # todo
    ContentIntake.objects.create(workspace=workspace, external_id="K2", pillar_theme="AI",
        sensitivity="public_safe", status="drafting")      # in_progress
    ContentIntake.objects.create(workspace=workspace, external_id="K3", pillar_theme="Agri",
        sensitivity="public_safe", status="scheduled")     # done
    from django.urls import reverse
    resp = authed.get(reverse("console:intake-board") + "?view=board")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "kanban-col-todo" in body
    assert "kanban-col-in_progress" in body
    assert "kanban-col-done" in body


@pytest.mark.django_db
def test_panel_shows_edit_link_when_post_exists(authed, workspace):
    from apps.content_intake.models import ContentIntake
    from apps.composer.models import Post
    post = Post.objects.create(workspace=workspace, title="t", caption="c")
    item = ContentIntake.objects.create(workspace=workspace, external_id="E1", angle="x",
        sensitivity="public_safe", status="drafting", post=post)
    from django.urls import reverse
    resp = authed.get(reverse("console:intake-row-panel", args=[item.pk]))
    assert resp.status_code == 200
    assert f"/workspace/{workspace.pk}/compose/{post.pk}/".encode() in resp.content


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["", "?view=board"])
def test_board_shows_content_pipeline_progress_strip(authed, workspace, query):
    """Both the table and kanban board views render the unified content-pipeline
    progress strip: total + a % through the pipeline + stage legend."""
    from apps.composer.models import Post
    ContentIntake.objects.create(workspace=workspace, external_id="cur",
        sensitivity="public_safe", status=ContentIntake.Status.ACCEPTED)
    ContentIntake.objects.create(workspace=workspace, external_id="pub",
        sensitivity="public_safe", status=ContentIntake.Status.PUBLISHED)
    Post.objects.create(workspace=workspace, caption="standalone")  # created

    resp = authed.get(reverse("console:intake-board") + query)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Content pipeline" in body
    assert "through pipeline" in body
    for label in ("Curated", "Published"):
        assert label in body
    assert "3" in body  # 2 curated + 1 created


@pytest.mark.django_db
def test_board_progress_strip_excludes_skipped_intake(authed, workspace):
    """Skipped intake is dead content — it is not counted in the progress total."""
    ContentIntake.objects.create(workspace=workspace, external_id="ok",
        sensitivity="public_safe", status=ContentIntake.Status.ACCEPTED)
    ContentIntake.objects.create(workspace=workspace, external_id="skip",
        sensitivity="public_safe", status=ContentIntake.Status.SKIPPED)
    resp = authed.get(reverse("console:intake-board"))
    body = resp.content.decode()
    # only the accepted one counts → singular "piece", not "pieces"
    assert "piece of content" in body
    assert "pieces of content" not in body
