from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import path

app_name = "console"


@login_required
def home(request):
    return redirect("console:ideas")


urlpatterns = [
    path("", home, name="home"),
    # ideas/drafts/approvals/pipeline/brain/graph.json/notifications added in G'3-G'6
]
