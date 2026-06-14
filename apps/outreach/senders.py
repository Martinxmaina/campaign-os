"""The guarded outreach sender — the single deliverability chokepoint.

``guarded_send`` is the *only* place outbound email becomes real. Deliverability
is enforced **here, in the adapter** (never in views): suppression → cap/ramp →
unsubscribe injection → send → per-day count → ``crm.Activity``. The gate stays
authoritative upstream (Task 4): ``guarded_send`` receives an already-issued
``gate_id`` and records it on the Activity; a non-pass body never reaches this
function because the gate orchestration raises ``GateBlocked`` first.

Transports are pluggable behind a tiny protocol:

- ``GmailEmailSender`` — the live sender; builds the per-owner Gmail service from
  the mailbox's ``GoogleIntegration`` and delegates to
  ``integrations.gmail.send_message``.
- ``InstantlyEmailSender`` — a stub seam (raises ``NotImplementedError``).

The google client libs stay lazily imported inside ``integrations.gmail`` — this
module only references the two pure functions, so importing it never requires
``google``.
"""
from __future__ import annotations

from typing import Protocol

from django.conf import settings
from django.core import signing
from django.db.models import F
from django.utils import timezone

from apps.outreach.exceptions import AddressSuppressed, CapExceeded
from apps.outreach.models import MailboxSend, SuppressionEntry
from integrations.gmail import build_gmail_service, send_message

# Salt for the unsubscribe token (the public unsubscribe view in Task 8 verifies
# the same salt). Kept here so the footer/header are forward-compatible.
UNSUBSCRIBE_SALT = "outreach-unsubscribe"


class EmailSender(Protocol):
    """A pluggable outbound transport. ``send`` returns the provider message id."""

    def send(self, integration, *, to: str, subject: str, body_html: str,
             sender: str | None = ..., headers: dict | None = ...) -> str:
        ...


class GmailEmailSender:
    """Live sender: per-owner Gmail via the mailbox's GoogleIntegration."""

    def send(self, integration, *, to, subject, body_html, sender=None, headers=None) -> str:
        service = build_gmail_service(integration)
        return send_message(
            service,
            to=to,
            subject=subject,
            body_html=body_html,
            sender=sender,
            headers=headers,
        )


class InstantlyEmailSender:
    """Stub seam for a future Instantly transport — not wired yet."""

    def send(self, integration, *, to, subject, body_html, sender=None, headers=None) -> str:
        raise NotImplementedError("Instantly transport is a stub; use GmailEmailSender.")


def _base_url() -> str:
    """Best-effort public base URL for unsubscribe links (no hard dependency)."""
    url = (getattr(settings, "STUDIO_BASE_URL", "") or "").strip().rstrip("/")
    if url:
        return url
    hosts = [h for h in getattr(settings, "ALLOWED_HOSTS", []) if h and h not in ("*",)]
    if hosts:
        return f"https://{hosts[0]}"
    return "https://localhost"


def make_unsubscribe_token(email: str) -> str:
    """Signed, tamper-proof token encoding the recipient address (Task 8 verifies)."""
    return signing.dumps({"email": email}, salt=UNSUBSCRIBE_SALT)


def _unsubscribe_url(email: str) -> str:
    return f"{_base_url()}/unsubscribe/{make_unsubscribe_token(email)}/"


def _inject_unsubscribe(body_html: str, to: str) -> tuple[str, dict]:
    """Append the unsubscribe footer and build the ``List-Unsubscribe`` header.

    Returns ``(body_with_footer, extra_headers)``. Per RFC 8058 / 2369 the header
    carries both a one-click https URL and a mailto fallback.
    """
    url = _unsubscribe_url(to)
    footer = (
        '<hr><p style="font-size:12px;color:#888">'
        f'You are receiving this from AfCEN / WAIIS. '
        f'<a href="{url}">Unsubscribe</a>.'
        "</p>"
    )
    headers = {
        "List-Unsubscribe": f"<{url}>, <mailto:unsubscribe@africacen.org?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    return body_html + footer, headers


def _ramp_week(mailbox) -> int:
    """Warm-up week index from ``ramp_started_at`` (``days // 7``); 0 if unset."""
    if not mailbox.ramp_started_at:
        return 0
    delta = timezone.now() - mailbox.ramp_started_at
    return max(delta.days, 0) // 7


def guarded_send(
    mailbox,
    *,
    to: str,
    subject: str,
    body: str,
    thread,
    gate_id: str,
    sender: EmailSender | None = None,
    extra_headers: dict | None = None,
) -> str:
    """Send one outbound email through all deliverability guards.

    Order (all enforced here, never in views):

      1. **Suppression** — a ``SuppressionEntry`` for ``to`` (case-insensitive)
         raises ``AddressSuppressed`` *before the transport is touched*.
      2. **Cap / ramp** — today's ``MailboxSend.count`` at or above the mailbox's
         ``effective_cap_for(ramp_week)`` raises ``CapExceeded``, transport untouched.
      3. **Unsubscribe** — the body gets an unsubscribe footer and a
         ``List-Unsubscribe`` header injected.
      4. **Send** — the (Gmail by default) transport is called.
      5. **Count** — today's per-day ``MailboxSend`` is incremented atomically.
      6. **Activity** — a ``crm.Activity(activity_type="email_sent")`` is written on
         the thread, carrying ``gate_id`` + the provider ``message_id``.

    ``gate_id`` is the verdict id from the upstream gate (Task 4) — recorded, not
    re-checked. Returns the transport message id.
    """
    # 1. suppression — fail closed, before any transport work
    if SuppressionEntry.objects.filter(email__iexact=to).exists():
        raise AddressSuppressed(to)

    # 2. cap / ramp
    today = timezone.localdate()
    cap = mailbox.effective_cap_for(_ramp_week(mailbox))
    current = MailboxSend.objects.filter(mailbox=mailbox, date=today).first()
    sent_today = current.count if current else 0
    if sent_today >= cap:
        raise CapExceeded(f"{mailbox.email}: {sent_today}/{cap} for {today}")

    # 3. unsubscribe injection (footer + List-Unsubscribe header)
    body_html, unsub_headers = _inject_unsubscribe(body, to)
    headers = {**unsub_headers, **(extra_headers or {})}

    # 4. send via the (Gmail) transport
    transport: EmailSender = sender or GmailEmailSender()
    message_id = transport.send(
        getattr(mailbox, "google_integration", None),
        to=to,
        subject=subject,
        body_html=body_html,
        sender=mailbox.email,
        headers=headers,
    )

    # 5. increment the per-day counter (atomic)
    if current:
        MailboxSend.objects.filter(pk=current.pk).update(count=F("count") + 1)
    else:
        MailboxSend.objects.create(mailbox=mailbox, date=today, count=1)

    # 6. log the send as a crm.Activity on the thread
    from apps.crm.models import Activity

    Activity.objects.create(
        thread=thread,
        activity_type="email_sent",
        actor_type="agent",
        agent_name="outreach",
        content_ref={
            "gate_id": gate_id,
            "message_id": message_id,
            "to": to,
            "subject": subject,
            "mailbox": mailbox.email,
        },
    )

    return message_id
