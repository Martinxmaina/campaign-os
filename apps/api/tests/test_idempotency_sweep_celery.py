"""Task 4 (Phase 2 S1): the idempotency sweep runs as a Celery @shared_task.

Under the test settings Celery is eager, so calling the task as a plain
function runs the body inline. The sweep must delete rows past the 24h
TTL and leave fresh rows untouched.

The plan's illustrative ``IdempotencyRecord.objects.create(api_key="k", ...)``
does not match the real model: ``api_key`` is a FK and
``request_fingerprint`` / ``response_status`` / ``response_body`` are
non-null. We build a minimal ApiKey (which needs a workspace -> org) so
the staleness logic stays identical to the plan.
"""

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
