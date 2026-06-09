from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import path

from apps.composer import console_views as composer_console

app_name = "console"


@login_required
def home(request):
    return redirect("console:ideas")


urlpatterns = [
    path("", home, name="home"),
    path("ideas", composer_console.ideas, name="ideas"),
    path("ideas/<str:idea_id>/decide", composer_console.idea_decide, name="idea-decide"),
    # drafts/approvals/pipeline/brain/graph.json/notifications added in G'4-G'6
]
