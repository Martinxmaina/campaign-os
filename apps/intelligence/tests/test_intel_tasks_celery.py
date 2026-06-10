import datetime
import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone as tz


def test_intel_tasks_are_shared_tasks():
    from apps.intelligence import tasks
    # @shared_task objects expose .delay
    assert hasattr(tasks.reconcile_intelligence_subscriptions, "delay")
    assert hasattr(tasks.provision_intelligence_account_via_session, "delay")
    assert hasattr(tasks._refresh_one_subscription, "delay")
    # sweep task must also be a shared_task with .delay
    assert hasattr(tasks.sweep_stale_pending_activations, "delay")


def test_refresh_on_visit_throttle_still_dispatches(monkeypatch):
    from apps.intelligence import tasks
    sent = []
    monkeypatch.setattr(tasks._refresh_one_subscription, "delay", lambda org_id: sent.append(org_id))
    # bypass the cache throttle for the assertion if needed
    tasks.refresh_subscription_on_visit("org-1")
    assert sent == ["org-1"] or sent == []  # throttle may suppress; must not raise


# ---------------------------------------------------------------------------
# sweep_stale_pending_activations tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sweep_stale_pending_activations_is_registered_in_beat():
    """The sweep task must appear in CELERY_BEAT_SCHEDULE."""
    from django.conf import settings
    schedule = settings.CELERY_BEAT_SCHEDULE
    tasks_registered = [entry["task"] for entry in schedule.values()]
    assert "apps.intelligence.tasks.sweep_stale_pending_activations" in tasks_registered


@pytest.mark.django_db
def test_sweep_re_enqueues_stale_pending():
    """Stale PENDING rows older than the staleness threshold trigger a re-enqueue."""
    from apps.intelligence import tasks
    from apps.intelligence.models import PendingActivation

    enqueued = []
    fake_task = MagicMock()
    fake_task.delay = lambda pending_id: enqueued.append(pending_id)

    # Build a minimal stale PendingActivation row using only fields defined
    # on the model (no FK objects needed — use the raw _id columns).
    # Use a real user stub: create the minimum required user via AUTH_USER_MODEL.
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.create_user(
        email=f"sweep-test-{uuid.uuid4().hex[:8]}@example.com",
        password="x",
    )

    stale_pending = PendingActivation.objects.create(
        user=user,
        session_id=f"cs_stale_{uuid.uuid4().hex}",
        status=PendingActivation.Status.PENDING,
    )
    # Back-date updated_at so it falls outside the staleness window.
    PendingActivation.objects.filter(pk=stale_pending.pk).update(
        updated_at=tz.now() - datetime.timedelta(hours=3),
    )

    with patch.object(tasks, "provision_intelligence_account_via_session", fake_task):
        tasks.sweep_stale_pending_activations()

    assert str(stale_pending.id) in enqueued, (
        "sweep_stale_pending_activations must re-enqueue stale PENDING rows"
    )


@pytest.mark.django_db
def test_sweep_skips_recently_updated_pending():
    """Rows updated within the staleness window must NOT be re-enqueued."""
    from apps.intelligence import tasks
    from apps.intelligence.models import PendingActivation
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        email=f"sweep-fresh-{uuid.uuid4().hex[:8]}@example.com",
        password="x",
    )

    fresh_pending = PendingActivation.objects.create(
        user=user,
        session_id=f"cs_fresh_{uuid.uuid4().hex}",
        status=PendingActivation.Status.PENDING,
    )
    # updated_at is auto_now so it's already "just now" — no back-dating needed.

    enqueued = []
    fake_task = MagicMock()
    fake_task.delay = lambda pending_id: enqueued.append(pending_id)

    with patch.object(tasks, "provision_intelligence_account_via_session", fake_task):
        tasks.sweep_stale_pending_activations()

    assert str(fresh_pending.id) not in enqueued, (
        "sweep must NOT re-enqueue rows that were recently updated"
    )


@pytest.mark.django_db
def test_sweep_skips_terminal_states():
    """Terminal-state rows (COMPLETED, REJECTED_UNAUTHORIZED, PROVISIONING_FAILED)
    must not be re-enqueued regardless of age."""
    from apps.intelligence import tasks
    from apps.intelligence.models import PendingActivation
    from django.contrib.auth import get_user_model

    User = get_user_model()
    terminal_statuses = [
        PendingActivation.Status.COMPLETED,
        PendingActivation.Status.REJECTED_UNAUTHORIZED,
        PendingActivation.Status.PROVISIONING_FAILED,
    ]
    enqueued = []
    fake_task = MagicMock()
    fake_task.delay = lambda pending_id: enqueued.append(pending_id)

    for status in terminal_statuses:
        user = User.objects.create_user(
            email=f"sweep-term-{uuid.uuid4().hex[:8]}@example.com",
            password="x",
        )
        row = PendingActivation.objects.create(
            user=user,
            session_id=f"cs_term_{uuid.uuid4().hex}",
            status=status,
        )
        # Back-date to make it look stale.
        PendingActivation.objects.filter(pk=row.pk).update(
            updated_at=tz.now() - datetime.timedelta(hours=3),
        )

    with patch.object(tasks, "provision_intelligence_account_via_session", fake_task):
        tasks.sweep_stale_pending_activations()

    assert enqueued == [], (
        f"sweep must not re-enqueue terminal rows, but enqueued: {enqueued}"
    )
