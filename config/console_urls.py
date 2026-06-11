from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import path

from apps.composer import console_views as composer_console
from apps.approvals import console_views as approvals_console
from apps.content_intake import views as intake_views
from apps.intelligence import console_views as intel_console

app_name = "console"


@login_required
def home(request):
    return redirect("console:ideas")


urlpatterns = [
    path("", home, name="home"),
    path("ideas", composer_console.ideas, name="ideas"),
    path("ideas/<str:idea_id>/decide", composer_console.idea_decide, name="idea-decide"),
    path("drafts", composer_console.drafts, name="drafts"),
    path("drafts/<str:content_id>", composer_console.draft_detail, name="draft-detail"),
    path("approvals", approvals_console.ai_approvals, name="approvals"),
    path("approvals/<str:approval_id>/decide", approvals_console.approval_decide, name="approval-decide"),
    path("pipeline", intel_console.pipeline, name="pipeline"),
    path("notifications", intel_console.notifications, name="notifications"),
    path("notifications/<str:notification_id>/read", intel_console.notification_read, name="notification-read"),
    path("brain", intel_console.brain, name="brain"),
    path("news", intel_console.news, name="news"),
    path("news/draft", intel_console.news_draft, name="news-draft"),
    path("graph.json", intel_console.graph_json, name="graph-json"),
    # Content intake board
    path("intake/", intake_views.board, name="intake-board"),
    path("intake/sync-now/", intake_views.sync_now, name="intake-sync-now"),
    path("intake/add-to-calendar/", intake_views.add_to_calendar, name="intake-add-to-calendar"),
    path("intake/draft-selected/", intake_views.draft_selected, name="intake-draft-selected"),
    path("intake/conditions/<uuid:condition_pk>/close/", intake_views.close_condition, name="intake-close-condition"),
    path("intake/<uuid:intake_pk>/draft/", intake_views.draft_now, name="intake-draft-now"),
    path("intake/<uuid:intake_pk>/draft-panel/", intake_views.draft_now_panel, name="intake-draft-now-panel"),
    # NOT-YET-WIRED: move_stage has no client. The intake board is table-based
    # (_table.html/_row.html), not a drag/drop Kanban — no template posts to this
    # endpoint and no drag handler exists, so the only callers today are tests. The
    # route is kept registered (the view's stage transitions are guarded and tested,
    # ready the moment a client lands) but it is NOT surfaced in any UI. When the
    # Kanban drag/drop lane UI is built, wire the drop handler to POST
    # to_stage=todo|in_progress|done here; until then there is no live path that
    # reaches it from the board.
    path("intake/<uuid:intake_pk>/stage/", intake_views.move_stage, name="intake-move-stage"),
    path("intake/<uuid:intake_pk>/panel/", intake_views.row_panel, name="intake-row-panel"),
]
