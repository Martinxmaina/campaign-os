"""Tests for apps.outreach core models — the outreach engine's deliverability spine.

Three models: Mailbox (a per-owner Gmail sending identity with a daily cap +
warm-up ramp), MailboxSend (the per-day send counter, unique on (mailbox, date)),
and SuppressionEntry (an opted-out / bounced address, unique on email). These
assert round-trip persistence, the unique constraints, defaults, the optional
GoogleIntegration link, and the warm-up ramp helper ``effective_cap_for``.
"""
from datetime import date

import pytest
from django.contrib import admin
from django.db import IntegrityError
from django.utils import timezone


def _make_user(email="owner@waiis.test"):
    from apps.accounts.models import User

    return User.objects.create_user(
        email=email, password="x", name="Owner", tos_accepted_at=timezone.now()
    )


@pytest.mark.django_db
def test_mailbox_round_trip_and_defaults():
    from apps.outreach.models import Mailbox

    user = _make_user()
    mb = Mailbox.objects.create(user=user, email="joseph@africacen.org")
    fetched = Mailbox.objects.get(pk=mb.pk)
    assert fetched.user_id == user.id
    assert fetched.email == "joseph@africacen.org"
    # default daily cap is 50
    assert fetched.daily_cap == 50
    # link to a GoogleIntegration is optional (null ok)
    assert fetched.google_integration is None
    # status defaults to active
    assert fetched.status == "active"
    # uuid pk + timestamps from the shared base
    assert fetched.id is not None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


@pytest.mark.django_db
def test_mailbox_optional_google_integration_link():
    from apps.joseph.models import GoogleIntegration
    from apps.outreach.models import Mailbox

    user = _make_user("gi@waiis.test")
    gi = GoogleIntegration.objects.create(user=user, refresh_token="1//rt", scopes=["s"])
    mb = Mailbox.objects.create(user=user, email="gi@africacen.org", google_integration=gi)
    assert Mailbox.objects.get(pk=mb.pk).google_integration_id == gi.id


@pytest.mark.django_db
def test_mailbox_effective_cap_ramp():
    """Warm-up ramp: week 0 → 20, week 1 → 35, week 2+ → daily_cap (50)."""
    from apps.outreach.models import Mailbox

    mb = Mailbox(user=None, email="ramp@africacen.org", daily_cap=50)
    assert mb.effective_cap_for(0) == 20
    assert mb.effective_cap_for(1) == 35
    assert mb.effective_cap_for(2) == 50
    assert mb.effective_cap_for(5) == 50


@pytest.mark.django_db
def test_mailbox_effective_cap_respects_custom_daily_cap():
    from apps.outreach.models import Mailbox

    mb = Mailbox(user=None, email="custom@africacen.org", daily_cap=80)
    # ramp weeks are fixed; only week 2+ uses the configured cap
    assert mb.effective_cap_for(0) == 20
    assert mb.effective_cap_for(1) == 35
    assert mb.effective_cap_for(2) == 80


@pytest.mark.django_db
def test_mailboxsend_round_trip_and_unique_per_day():
    from apps.outreach.models import Mailbox, MailboxSend

    user = _make_user("send@waiis.test")
    mb = Mailbox.objects.create(user=user, email="send@africacen.org")
    today = date(2026, 6, 15)
    ms = MailboxSend.objects.create(mailbox=mb, date=today, count=3)
    fetched = MailboxSend.objects.get(pk=ms.pk)
    assert fetched.mailbox_id == mb.id
    assert fetched.date == today
    assert fetched.count == 3

    # unique on (mailbox, date): a second row for the same day is rejected
    with pytest.raises(IntegrityError):
        MailboxSend.objects.create(mailbox=mb, date=today, count=1)


@pytest.mark.django_db
def test_suppression_entry_round_trip_and_unique_email():
    from apps.outreach.models import SuppressionEntry

    s = SuppressionEntry.objects.create(email="x@y.org", reason="unsubscribe")
    fetched = SuppressionEntry.objects.get(pk=s.pk)
    assert fetched.email == "x@y.org"
    assert fetched.reason == "unsubscribe"
    assert fetched.created_at is not None

    # email is unique
    with pytest.raises(IntegrityError):
        SuppressionEntry.objects.create(email="x@y.org", reason="bounce")


@pytest.mark.django_db
def test_models_registered_in_admin():
    from apps.outreach.models import Mailbox, MailboxSend, SuppressionEntry

    assert admin.site.is_registered(Mailbox)
    assert admin.site.is_registered(MailboxSend)
    assert admin.site.is_registered(SuppressionEntry)
