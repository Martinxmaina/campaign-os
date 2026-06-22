from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import path

from apps.composer import console_views as composer_console
from apps.composer import studio_views as composer_studio
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
    # Content Studio — the unified content board (collapses the 4 draft surfaces).
    path("content", composer_studio.content_studio, name="content"),
    path("approvals", approvals_console.ai_approvals, name="approvals"),
    path("approvals/<str:approval_id>/decide", approvals_console.approval_decide, name="approval-decide"),
    path("pipeline", intel_console.pipeline, name="pipeline"),
    path("notifications", intel_console.notifications, name="notifications"),
    path("notifications/<str:notification_id>/read", intel_console.notification_read, name="notification-read"),
    path("brain", intel_console.brain, name="brain"),
    # Agent-brain Learning Log + diff-review (Loop 2). Reads owner/admin-gated;
    # apply/reject mirror the lead-gated agent-service /brain/* mutations.
    path("learning/", intel_console.learning_log, name="learning-log"),
    path("diffs/", intel_console.diff_list, name="diff-list"),
    path("diffs/<str:proposal_id>/", intel_console.diff_detail, name="diff-detail"),
    path("diffs/<str:proposal_id>/apply", intel_console.diff_apply, name="diff-apply"),
    path("diffs/<str:proposal_id>/reject", intel_console.diff_reject, name="diff-reject"),
    # Agent-brain fleet + breakers + healing (Slice 2). Reads owner/admin-gated;
    # breaker Reset mirrors the lead-gated agent-service /breakers/<id>/reset.
    path("agents/", intel_console.agents_fleet, name="agents-fleet"),
    path("breakers/", intel_console.breakers, name="breakers"),
    path("breakers/<str:breaker_id>/reset", intel_console.breaker_reset, name="breaker-reset"),
    path("healing/", intel_console.healing, name="healing"),
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
    # Kanban drag-to-restage. The Board view (board_kanban.html, reached via
    # ?view=board) drops POST here with to_stage=todo|in_progress|done. The view
    # ONLY changes status — it NEVER drafts (drafting is the manual draft_now
    # action). Stage transitions are guarded against demoting terminal items.
    path("intake/<uuid:intake_pk>/stage/", intake_views.move_stage, name="intake-move-stage"),
    path("intake/<uuid:intake_pk>/panel/", intake_views.row_panel, name="intake-row-panel"),
]
