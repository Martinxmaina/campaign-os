from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.members.decorators import require_org_role
from apps.members.models import OrgMembership


@login_required
@require_org_role(OrgMembership.OrgRole.ADMIN)
def settings_view(request):
    org = request.org
    return render(request, "organizations/settings.html", {"organization": org})
