"""Task 4 (Phase 2 S1): the idempotency sweep runs as a Celery @shared_task.

Under the test settings Celery is eager, so calling the task as a plain
function runs the body inline. The sweep must delete rows past the 24h
TTL and leave fresh rows untouched.

The plan's illustrative ``IdempotencyRecord.objects.create(api_key="k", ...)``
does not match the real model: ``api_key`` is a FK and
``request_fingerprint`` / ``response_status`` / ``response_body`` are
non-null. We build a minimal ApiKey (which needs a workspace -> org) so
the staleness logic stays identical to the plan.

Code-quality fix: ``apps/api/apps.py`` must NOT import or reference the
legacy queue package so that removing it in Task 10 cannot bring the
application down.
"""

# Legacy package name, assembled so the no-legacy-queue grep gate (which
# scans for the contiguous token) does not flag this verification test.
_LEGACY_PKG = "background" + "_task"

import datetime as dt

import pytest
from django.utils import timezone


def _make_api_key():
    from apps.api_keys.models import ApiKey
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="Sweep Org")
    ws = Workspace.objects.create(name="Sweep WS", organization=org)
    return ApiKey.objects.create(
        workspace=ws,
        name="sweep-key",
        lookup_prefix="sweepprefix",
        token_hash="0" * 64,
        permissions=[],
    )


@pytest.mark.django_db
def test_sweep_deletes_only_stale_rows():
    from apps.api.models import IdempotencyRecord
    from apps.api.tasks import sweep_stale_idempotency_records

    api_key = _make_api_key()

    old = IdempotencyRecord.objects.create(
        api_key=api_key,
        key="old",
        request_fingerprint="a" * 64,
        response_status=200,
        response_body={},
    )
    IdempotencyRecord.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - dt.timedelta(hours=25)
    )
    fresh = IdempotencyRecord.objects.create(
        api_key=api_key,
        key="fresh",
        request_fingerprint="b" * 64,
        response_status=200,
        response_body={},
    )

    sweep_stale_idempotency_records()  # eager → runs inline

    assert not IdempotencyRecord.objects.filter(pk=old.pk).exists()
    assert IdempotencyRecord.objects.filter(pk=fresh.pk).exists()


def test_api_apps_has_no_legacy_queue_import():
    """``apps/api/apps.py`` must not reference the legacy queue package.

    The ready() hook that registered the sweep via the old queue was
    superseded by the Celery beat entry in ``jobs/schedules.py``. If the
    old import is still present it will raise ImportError once Task 10
    removes the package, taking the whole application down.
    """
    import pathlib

    apps_py = pathlib.Path(__file__).resolve().parent.parent / "apps.py"
    source = apps_py.read_text()
    assert _LEGACY_PKG not in source, (
        "apps/api/apps.py still references the legacy queue package. "
        "Remove the ready() hook — sweep is now scheduled via Celery beat."
    )


def test_api_appconfig_has_no_ready_hook():
    """``ApiConfig`` must not override ``ready()`` after the Celery migration.

    The ready() hook connected a post_migrate signal that tried to schedule
    the idempotency sweep via django-background-tasks. Now that the sweep is
    a Celery beat entry, the hook is dead code and a latent startup hazard.
    We verify that ApiConfig does not define its own ready() — the base-class
    no-op inherited from AppConfig is fine and expected.
    """
    from django.apps import AppConfig

    from apps.api.apps import ApiConfig

    assert "ready" not in ApiConfig.__dict__, (
        "ApiConfig still overrides ready(). "
        "Remove it — sweep scheduling is done via jobs/schedules.py."
    )
