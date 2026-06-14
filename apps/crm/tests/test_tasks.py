"""Tests for the ported DEAL-ENGINE Celery tasks: daily scoring + no-reply.

Parity intent: ``flag_no_reply`` mirrors agent-service
``app/services/sequences.py::run_no_reply`` thresholds (amber >14d, red >28d
on ``last_touch``), and ``score_all_threads`` persists the
``apps.crm.scoring.score_thread_features`` result on every open thread.
"""
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.crm.models import Organization, OutreachThread
from apps.crm.tasks import flag_no_reply, score_all_threads

User = get_user_model()


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="n@africacen.org", password="x", name="Nduta")


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Rockefeller", type="funder")


def _thread(org, owner, **kw):
    return OutreachThread.objects.create(org=org, owner=owner, **kw)


# --------------------------------------------------------------------------- #
# flag_no_reply
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_flag_no_reply_sets_amber_at_15_days(org, owner):
    now = timezone.now()
    t = _thread(org, owner, stage="engaged", traffic_light="green",
                last_touch=now - timedelta(days=15))

    flag_no_reply()

    t.refresh_from_db()
    assert t.traffic_light == "amber"


@pytest.mark.django_db
def test_flag_no_reply_sets_red_at_29_days(org, owner):
    now = timezone.now()
    t = _thread(org, owner, stage="engaged", traffic_light="green",
                last_touch=now - timedelta(days=29))

    flag_no_reply()

    t.refresh_from_db()
    assert t.traffic_light == "red"


@pytest.mark.django_db
def test_flag_no_reply_leaves_recent_thread_green(org, owner):
    now = timezone.now()
    t = _thread(org, owner, stage="engaged", traffic_light="green",
                last_touch=now - timedelta(days=3))

    flag_no_reply()

    t.refresh_from_db()
    assert t.traffic_light == "green"


@pytest.mark.django_db
def test_flag_no_reply_skips_closed_stage(org, owner):
    now = timezone.now()
    t = _thread(org, owner, stage="closed", traffic_light="green",
                last_touch=now - timedelta(days=40))

    flag_no_reply()

    t.refresh_from_db()
    assert t.traffic_light == "green"


@pytest.mark.django_db
def test_flag_no_reply_ignores_threads_without_last_touch(org, owner):
    t = _thread(org, owner, stage="engaged", traffic_light="green", last_touch=None)

    flag_no_reply()

    t.refresh_from_db()
    assert t.traffic_light == "green"


# --------------------------------------------------------------------------- #
# score_all_threads
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_score_all_threads_writes_score_quintile_traffic(org, owner):
    now = timezone.now()
    # Hot, senior, recently touched → high feature values → high score.
    t = _thread(
        org, owner, stage="engaged", warmth="hot",
        track="ai10bn", pillar="ai10bn",
        last_touch=now - timedelta(days=1),
    )
    t.primary_contact = None
    t.save()

    score_all_threads()

    t.refresh_from_db()
    assert t.score > 0.0
    assert 1 <= t.quintile <= 5
    assert t.traffic_light in {"green", "amber", "red"}


@pytest.mark.django_db
def test_score_all_threads_cold_old_scores_lower_than_hot_recent(org, owner):
    now = timezone.now()
    hot = _thread(org, owner, stage="engaged", warmth="hot",
                  last_touch=now - timedelta(days=1))
    cold = _thread(org, owner, stage="targeted", warmth="cold",
                   last_touch=now - timedelta(days=60))

    score_all_threads()

    hot.refresh_from_db()
    cold.refresh_from_db()
    assert hot.score > cold.score


# --------------------------------------------------------------------------- #
# beat registration
# --------------------------------------------------------------------------- #
def test_tasks_registered_in_beat():
    registered = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert "apps.crm.tasks.score_all_threads" in registered
    assert "apps.crm.tasks.flag_no_reply" in registered
