"""Thread send + sequence enroll + reply-triage queue + suppression + unsubscribe.

The operator-facing surfaces over the outreach engine (Task 8). Every view but
the public unsubscribe is role-gated by ``_can_manage_outreach`` (staff or an
owner/admin/campaign_owner workspace role — shared with the mailbox views).

  POST /outreach/threads/<id>/send/    → ``thread_send``    : gate → guarded_send
  POST /outreach/threads/<id>/enroll/  → ``thread_enroll``  : enroll a sequence
  GET  /outreach/triage/               → ``triage_queue``   : reply-triage items
  GET  /outreach/suppression/          → ``suppression_list``: list entries
  POST /outreach/suppression/add/      → ``suppression_add``
  POST /outreach/suppression/<id>/remove/ → ``suppression_remove``
  GET  /unsubscribe/<token>/           → ``unsubscribe``    : PUBLIC (no auth)

GATE INVARIANT: ``thread_send`` never touches a transport itself — it calls the
gated ``apps.outreach.gating.send_email`` orchestrator, which gates the body and
only then delegates to the deliverability adapter ``guarded_send``. A non-pass
body raises ``GateBlocked`` (an approval Activity is queued inside ``send_email``)
and the transport is never reached; the view catches it and surfaces a message,
never a 500. Deliverability (suppression / cap / unsubscribe) lives entirely in
the adapter, not here.

The transport is built behind ``_build_sender`` so tests can inject a mock — the
view itself stays transport-agnostic. CSP-safe templates throughout (no inline
handlers); the unsubscribe view is public so a recipient can opt out without an
account.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.crm.models import OutreachThread
from apps.outreach.exceptions import GateBlocked, OutreachError
from apps.outreach.models import Mailbox, Sequence, SequenceStep, SuppressionEntry, SequenceTemplate
from apps.outreach.senders import UNSUBSCRIBE_SALT, EmailSender, GmailEmailSender
from apps.outreach.sequences import enroll
from apps.outreach.views import _can_manage_outreach

logger = logging.getLogger(__name__)


def _build_sender() -> EmailSender:
    """The live outbound transport — overridable in tests (mock injection).

    Kept a tiny indirection so the views never import a concrete transport at
    call time; ``thread_send`` always routes through the gated ``send_email``
    orchestrator, which enforces the GATE INVARIANT before this sender is reached.
    """
    return GmailEmailSender()


def _resolve_mailbox(thread):
    """The active sending mailbox for the thread's owner, or ``None``."""
    owner_id = getattr(thread, "owner_id", None)
    if not owner_id:
        return None
    return (
        Mailbox.objects.filter(user_id=owner_id, status=Mailbox.Status.ACTIVE)
        .order_by("created_at")
        .first()
    )


@login_required
@require_POST
def thread_send(request, thread_id):
    """Gate + send one outbound email on a thread.

    Delegates to the gated ``send_email`` orchestrator: the body is gated first
    and a non-pass verdict raises ``GateBlocked`` (an approval Activity is queued)
    before any transport is touched. Deliverability guards (suppression / cap /
    unsubscribe) live in ``guarded_send`` downstream. Every successful send writes
    a ``crm.Activity(email_sent)`` (inside the adapter). Never 500s on a block —
    the operator gets a clear message.
    """
    if not _can_manage_outreach(request):
        return HttpResponseForbidden("Outreach is not available for your role.")

    thread = get_object_or_404(OutreachThread, id=thread_id)

    subject = (request.POST.get("subject") or "").strip()
    body = (request.POST.get("body") or "").strip()
    if not body:
        messages.error(request, "Nothing to send — the body is empty.")
        return _respond(request, thread)

    mailbox = _resolve_mailbox(thread)
    if mailbox is None:
        messages.error(
            request, "No active mailbox for this thread's owner — connect one first."
        )
        return _respond(request, thread)

    # Import the orchestrator lazily so the view module never hard-requires the
    # gate/transport chain at import time.
    from apps.outreach.gating import send_email

    try:
        send_email(
            thread,
            subject=subject or "(no subject)",
            body=body,
            mailbox=mailbox,
            sender=_build_sender(),
        )
    except GateBlocked:
        # send_email already queued an approval-needed Activity; surface it.
        messages.error(
            request,
            "Blocked by the content gate — queued for approval. The email was not sent.",
        )
    except OutreachError as exc:
        # Suppression / cap / scope — the deliverability guard tripped.
        messages.error(request, f"Not sent: {exc}")
    else:
        messages.success(request, "Email sent.")

    return _respond(request, thread)


@login_required
@require_POST
def thread_enroll(request, thread_id):
    """Enroll a thread into a sequence template (creates a Sequence + steps)."""
    if not _can_manage_outreach(request):
        return HttpResponseForbidden("Outreach is not available for your role.")

    thread = get_object_or_404(OutreachThread, id=thread_id)
    template_id = (request.POST.get("template") or "").strip()
    template = SequenceTemplate.objects.filter(id=template_id).first() if template_id else None
    if template is None:
        messages.error(request, "Pick a sequence template to enroll.")
        return _respond(request, thread)

    seq = enroll(thread, template)
    messages.success(
        request, f"Enrolled in “{template.name}” — {seq.steps.count()} step(s) scheduled."
    )
    return _respond(request, thread)


@login_required
def triage_queue(request):
    """Reply-triage queue — threads with a recent inbound reply to action.

    Each item is the latest ``email_reply`` Activity per thread (newest first),
    annotated with whether the thread's sequence is paused (triage_inbound pauses
    on a reply). Pure Django read; no agent-service.
    """
    if not _can_manage_outreach(request):
        return HttpResponseForbidden("Outreach is not available for your role.")

    from apps.crm.models import Activity

    replies = (
        Activity.objects.filter(activity_type="email_reply")
        .select_related("thread", "thread__org", "thread__owner")
        .order_by("-created_at")[:100]
    )
    # Collapse to the most-recent reply per thread (keeps the queue one-row-per-deal).
    items = []
    seen = set()
    for act in replies:
        if act.thread_id in seen:
            continue
        seen.add(act.thread_id)
        items.append(act)

    return render(request, "outreach/triage_queue.html", {"items": items})


@login_required
def suppression_list(request):
    """The global suppression list (opted-out / bounced addresses)."""
    if not _can_manage_outreach(request):
        return HttpResponseForbidden("Outreach is not available for your role.")

    entries = SuppressionEntry.objects.order_by("-created_at")
    return render(request, "outreach/suppression_list.html", {"entries": entries})


@login_required
@require_POST
def suppression_add(request):
    """Add an address to the suppression list (idempotent, case-insensitive)."""
    if not _can_manage_outreach(request):
        return HttpResponseForbidden("Outreach is not available for your role.")

    email = (request.POST.get("email") or "").strip().lower()
    reason = (request.POST.get("reason") or "manual").strip() or "manual"
    if email:
        SuppressionEntry.objects.get_or_create(
            email=email, defaults={"reason": reason}
        )
        messages.success(request, f"{email} suppressed.")
    else:
        messages.error(request, "Enter an address to suppress.")
    return redirect("outreach:suppression")


@login_required
@require_POST
def suppression_remove(request, entry_id):
    """Remove an address from the suppression list (re-allow sending)."""
    if not _can_manage_outreach(request):
        return HttpResponseForbidden("Outreach is not available for your role.")

    SuppressionEntry.objects.filter(id=entry_id).delete()
    messages.success(request, "Removed from the suppression list.")
    return redirect("outreach:suppression")


def unsubscribe(request, token):
    """PUBLIC unsubscribe — verify the signed token, suppress the address.

    No authentication: a recipient must be able to opt out without an account.
    The token is the same ``signing.dumps({"email": ...}, salt=UNSUBSCRIBE_SALT)``
    minted by ``senders.make_unsubscribe_token`` and embedded in the email footer
    + ``List-Unsubscribe`` header. A tampered/expired token renders a graceful
    page (never a 500) and adds nothing. CSP-safe template.
    """
    email = None
    try:
        data = signing.loads(token, salt=UNSUBSCRIBE_SALT)
        email = (data.get("email") or "").strip().lower()
    except signing.BadSignature:
        logger.info("outreach.unsubscribe bad token")

    suppressed = False
    if email:
        SuppressionEntry.objects.get_or_create(
            email=email, defaults={"reason": "unsubscribe"}
        )
        suppressed = True

    return render(
        request,
        "outreach/unsubscribe.html",
        {"email": email, "suppressed": suppressed},
    )


def _respond(request, thread):
    """HTMX → bounce the actor back; full POST → return to the Joseph drawer.

    The send/enroll forms live in the Joseph thread drawer (and the CRM thread
    view); after the action we land the operator back on that drawer so the
    fresh timeline/sequence is visible. CSP-safe (plain redirect / 204 swap).
    """
    if getattr(request, "htmx", False):
        # Let HTMX refresh the page region it triggered from.
        from django.http import HttpResponse

        resp = HttpResponse(status=204)
        resp["HX-Refresh"] = "true"
        return resp
    return redirect(f"/joseph/thread/{thread.id}/")
