"""Outreach mailbox connect / status views (Task 7).

A single role-gated status surface over the deliverability spine:

  GET  /outreach/mailbox/                 → ``mailbox_status`` : per-mailbox cap,
        ramp week, today's send count, send-readiness (gmail.send scope), plus the
        global suppression count + a re-consent hint for grants missing the scope.
  POST /outreach/mailbox/<id>/pause/      → ``mailbox_pause``  : status → paused
  POST /outreach/mailbox/<id>/resume/     → ``mailbox_resume`` : status → active

Every view is gated by ``_can_manage_outreach`` (staff or an
owner/admin/campaign_owner workspace role — mirrors ``apps/crm._can_manage_crm``).
Pure Django querysets; NO transport is touched here (deliverability lives in the
adapter ``senders.guarded_send``). CSP-safe template: no inline handlers — the
pause/resume controls are plain ``hx-post`` forms / Alpine.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.outreach.models import Mailbox, MailboxSend, SuppressionEntry
from apps.outreach.senders import _ramp_week
from integrations.gmail import GMAIL_SEND_SCOPE


def _can_manage_outreach(request) -> bool:
    """Gate for the outreach surfaces — staff (superuser escape hatch) OR a
    workspace role of owner/admin/campaign_owner. Mirrors
    ``apps/crm.views_import._can_manage_crm`` (reuses the membership already
    resolved on the request by RBACMiddleware)."""
    if getattr(request.user, "is_staff", False):
        return True
    m = getattr(request, "workspace_membership", None)
    return bool(m and m.workspace_role in ("owner", "admin", "campaign_owner"))


def _mailbox_can_send(mailbox) -> bool:
    """True iff the mailbox is wired to send: a connected grant carrying
    ``gmail.send``. An unconnected mailbox (no integration) is *not* send-ready."""
    integration = getattr(mailbox, "google_integration", None)
    if integration is None:
        return False
    return GMAIL_SEND_SCOPE in (getattr(integration, "scopes", None) or [])


@login_required
def mailbox_status(request):
    """Per-mailbox deliverability dashboard (cap / ramp / today / send-readiness)."""
    if not _can_manage_outreach(request):
        return HttpResponseForbidden("Outreach is not available for your role.")

    today = timezone.localdate()
    counts = {
        row["mailbox_id"]: row["count"]
        for row in MailboxSend.objects.filter(date=today).values("mailbox_id", "count")
    }

    rows = []
    for mailbox in Mailbox.objects.select_related("google_integration", "user").order_by("email"):
        ramp_week = _ramp_week(mailbox)
        rows.append(
            {
                "mailbox": mailbox,
                "sent_today": counts.get(mailbox.id, 0),
                "ramp_week": ramp_week,
                "effective_cap": mailbox.effective_cap_for(ramp_week),
                "can_send": _mailbox_can_send(mailbox),
                "is_connected": mailbox.google_integration_id is not None,
            }
        )

    return render(
        request,
        "outreach/mailbox.html",
        {
            "mailboxes": rows,
            "suppression_count": SuppressionEntry.objects.count(),
            "gmail_send_scope": GMAIL_SEND_SCOPE,
        },
    )


@login_required
@require_POST
def mailbox_pause(request, mailbox_id):
    """Pause a mailbox — no further sends until resumed."""
    if not _can_manage_outreach(request):
        return HttpResponseForbidden("Outreach is not available for your role.")
    mailbox = get_object_or_404(Mailbox, id=mailbox_id)
    mailbox.status = Mailbox.Status.PAUSED
    mailbox.save(update_fields=["status", "updated_at"])
    return redirect("outreach:mailbox")


@login_required
@require_POST
def mailbox_resume(request, mailbox_id):
    """Resume a paused mailbox — sends may flow again (subject to cap/ramp)."""
    if not _can_manage_outreach(request):
        return HttpResponseForbidden("Outreach is not available for your role.")
    mailbox = get_object_or_404(Mailbox, id=mailbox_id)
    mailbox.status = Mailbox.Status.ACTIVE
    mailbox.save(update_fields=["status", "updated_at"])
    return redirect("outreach:mailbox")
