"""Public review views for approval-by-email (Task 5 implementation).

This module is a stub — routes are registered here so that
``reverse("approvals:review", ...)`` resolves in Task 4's
``assignment_service``.  The full implementation lives in Task 5.
"""
from django.http import HttpResponse


def review(request, token):
    """Public review page — implemented in Task 5."""
    return HttpResponse("review page placeholder", status=200)
