from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import path

from apps.composer import console_views as composer_console
from apps.approvals import console_views as approvals_console

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
    # pipeline/brain/graph.json/notifications added in G'5-G'6
]
