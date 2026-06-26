"""Tests for apps/approvals/emailer.py (Task 3: email transport seam)."""
import pytest
from django.core import mail


# ---------------------------------------------------------------------------
# (a) No Gmail integration → falls back to SMTP/locmem; returns True
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_email_no_integration_uses_locmem(settings):
    """With no GoogleIntegration, send_email uses the Django mail backend."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    from apps.approvals.emailer import send_email

    result = send_email("to@x.co", "S", "<b>h</b>")

    assert result is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["to@x.co"]


# ---------------------------------------------------------------------------
# (b) Integration present → Gmail path used; returns True
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_email_uses_gmail_when_integration_present(django_user_model, monkeypatch):
    """When a GoogleIntegration with the send scope exists, the Gmail path is taken."""
    from integrations.gmail import GMAIL_SEND_SCOPE
    from apps.joseph.models import GoogleIntegration
    from apps.approvals import emailer

    u = django_user_model.objects.create_user(
        email="owner@x.co", password="x", name="Owner"
    )
    GoogleIntegration.objects.create(
        user=u,
        refresh_token="rt",
        scopes=[GMAIL_SEND_SCOPE],
    )

    sent_calls = []

    def fake_build(integration):
        return object()  # sentinel service

    def fake_send(service, *, to, subject, body_html, sender=None):
        sent_calls.append({"to": to, "subject": subject, "html": body_html})
        return "msg-id-123"

    monkeypatch.setattr("apps.approvals.emailer._build_gmail_service", fake_build)
    monkeypatch.setattr("apps.approvals.emailer._send_gmail_message", fake_send)

    result = emailer.send_email("to@x.co", "Subj", "<p>hello</p>")

    assert result is True
    assert len(sent_calls) == 1
    assert sent_calls[0]["to"] == "to@x.co"


# ---------------------------------------------------------------------------
# (c) Both transports raise → send_email returns False, never raises
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_email_returns_false_when_both_transports_fail(
    django_user_model, monkeypatch
):
    """If Gmail raises AND SMTP raises, send_email returns False gracefully."""
    from integrations.gmail import GMAIL_SEND_SCOPE
    from apps.joseph.models import GoogleIntegration
    from apps.approvals import emailer

    u = django_user_model.objects.create_user(
        email="owner2@x.co", password="x", name="Owner2"
    )
    GoogleIntegration.objects.create(
        user=u,
        refresh_token="rt",
        scopes=[GMAIL_SEND_SCOPE],
    )

    def boom_build(integration):
        raise RuntimeError("gmail boom")

    def boom_smtp(subject, body, from_email, to, **kwargs):
        raise RuntimeError("smtp boom")

    monkeypatch.setattr("apps.approvals.emailer._build_gmail_service", boom_build)

    # Patch EmailMultiAlternatives.send to raise
    from django.core.mail import EmailMultiAlternatives

    monkeypatch.setattr(EmailMultiAlternatives, "send", lambda self: (_ for _ in ()).throw(RuntimeError("smtp boom")))

    result = emailer.send_email("to@x.co", "S", "<b>x</b>")

    assert result is False


# ---------------------------------------------------------------------------
# (d) Resend configured → Resend path used first; returns True
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_email_prefers_resend_when_configured(settings, monkeypatch):
    """When RESEND_API_KEY is set, send_email sends via Resend (not SMTP)."""
    settings.RESEND_API_KEY = "re_test"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    from apps.approvals import emailer

    calls = []
    monkeypatch.setattr(emailer, "_resend_send",
                        lambda to, subject, html: calls.append((to, subject)) or True)

    result = emailer.send_email("to@x.co", "Subj", "<p>hi</p>")

    assert result is True
    assert calls == [("to@x.co", "Subj")]
    assert len(mail.outbox) == 0  # SMTP not used


# ---------------------------------------------------------------------------
# (e) Resend fails → falls back to SMTP/locmem; returns True
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_email_falls_back_when_resend_fails(settings, monkeypatch):
    settings.RESEND_API_KEY = "re_test"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    from apps.approvals import emailer

    def boom(to, subject, html):
        raise RuntimeError("resend down")

    monkeypatch.setattr(emailer, "_resend_send", boom)

    result = emailer.send_email("to@x.co", "S", "<b>h</b>")

    assert result is True
    assert len(mail.outbox) == 1  # fell back to SMTP/locmem
