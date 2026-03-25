from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def member_list(request):
    return render(request, "members/list.html")
