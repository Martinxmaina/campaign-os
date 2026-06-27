from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def index(request, workspace_id):
    return render(request, "home/index.html", {"workspace": request.workspace})
