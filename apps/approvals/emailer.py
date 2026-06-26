"""Email transport seam for the approval-by-email flow (Task 3).

Prefer Gmail-OAuth (via ``apps.joseph.models.GoogleIntegration`` with the
gmail.send scope) and fall back to Django's configured mail backend (SMTP or
locmem in tests).  Never raises — callers can treat the return value as a
best-effort signal.

Module-level shims ``_build_gmail_service`` and ``_send_gmail_message`` are
thin wrappers imported from ``integrations.gmail`` and are monkeypatch-friendly
in tests.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Patchable shims — tests replace these; prod uses the real implementations.
# ---------------------------------------------------------------------------

def _build_gmail_service(integration):
    """Thin shim around ``integrations.gmail.build_gmail_service``."""
    from integrations.gmail import build_gmail_service

    return build_gmail_service(integration)


def _send_gmail_message(service, *, to, subject, body_html, sender=None):
    """Thin shim around ``integrations.gmail.send_message``."""
    from integrations.gmail import send_message

    return send_message(service, to=to, subject=subject, body_html=body_html,
                        sender=sender)


# ---------------------------------------------------------------------------
# Integration lookup
# ---------------------------------------------------------------------------

def _gmail_integration():
    """Return an admin GoogleIntegration that has the gmail.send scope, or None.

    ``scopes`` is a JSONField(default=list) storing the full OAuth scope URLs.
    We fetch candidates and check in Python to avoid SQLite/Postgres JSONField
    lookup differences.
    """
    try:
        from integrations.gmail import GMAIL_SEND_SCOPE
        from apps.joseph.models import GoogleIntegration

        for gi in GoogleIntegration.objects.all():
            if GMAIL_SEND_SCOPE in (gi.scopes or []):
                return gi
        return None
    except Exception:  # noqa: BLE001 — table may not exist yet during migrations
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _resend_send(to: str, subject: str, html: str) -> bool:
    """Send via the Resend HTTP API (https://resend.com). Returns True on 2xx.

    Used when ``settings.RESEND_API_KEY`` is configured. The ``from`` address is
    ``settings.DEFAULT_FROM_EMAIL`` and must be on a Resend-verified domain.
    """
    import httpx

    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"from": settings.DEFAULT_FROM_EMAIL, "to": [to], "subject": subject, "html": html},
        timeout=15.0,
    )
    resp.raise_for_status()
    return True


def send_email(to: str, subject: str, html: str) -> bool:
    """Send an HTML email. Prefer Resend (if configured), then Gmail-OAuth, then
    Django's SMTP/console backend.

    Returns True on success, False if every transport failed.  Never raises.
    """
    if getattr(settings, "RESEND_API_KEY", ""):
        try:
            return _resend_send(to, subject, html)
        except Exception:  # noqa: BLE001
            logger.warning("Resend send failed; falling back", exc_info=True)

    integration = _gmail_integration()
    if integration is not None:
        try:
            service = _build_gmail_service(integration)
            _send_gmail_message(
                service,
                to=to,
                subject=subject,
                body_html=html,
                sender=settings.DEFAULT_FROM_EMAIL or None,
            )
            return True
        except Exception:  # noqa: BLE001
            logger.warning("Gmail send failed; falling back to SMTP", exc_info=True)

    try:
        msg = EmailMultiAlternatives(
            subject, html, settings.DEFAULT_FROM_EMAIL, [to]
        )
        msg.attach_alternative(html, "text/html")
        msg.send()
        return True
    except Exception:  # noqa: BLE001
        logger.warning("SMTP send failed for %s", to, exc_info=True)
        return False
