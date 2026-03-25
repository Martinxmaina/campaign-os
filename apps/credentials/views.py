from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def credentials_list(request):
    return render(request, "credentials/list.html")
