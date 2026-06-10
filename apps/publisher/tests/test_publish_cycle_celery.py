import contextlib
import inspect

import pytest


@pytest.mark.django_db
def test_publish_cycle_invokes_engine(monkeypatch):
    from apps.publisher import tasks

    calls = {"n": 0}

    class FakeEngine:
        def poll_and_publish(self):
            calls["n"] += 1
            return 0

    monkeypatch.setattr("apps.publisher.engine.PublishEngine", lambda: FakeEngine())
    monkeypatch.setattr(
        "apps.publisher.tasks.redis_lock", lambda *a, **k: contextlib.nullcontext()
    )
    tasks.run_publish_cycle()
    assert calls["n"] == 1


def test_publish_cycle_lock_ttl_covers_soft_time_limit():
    """The lock TTL must be >= CELERY_TASK_SOFT_TIME_LIMIT (540 s).

    With TTL=60 and a 9-minute soft limit, the lock expires mid-cycle,
    allowing a second tick to start and double-publish.  The fix raises the
    TTL to cover the full soft-time window.
    """
    from django.conf import settings
    import apps.publisher.tasks as tasks_mod

    # Extract the ttl kwarg actually passed to redis_lock inside run_publish_cycle.
    source = inspect.getsource(tasks_mod.run_publish_cycle)
    # Find 'redis_lock("publish-cycle", ttl=NNN)' in the source.
    import re
    match = re.search(r'redis_lock\([^)]*ttl\s*=\s*(\d+)', source)
    assert match, "redis_lock call with explicit ttl not found in run_publish_cycle"
    actual_ttl = int(match.group(1))
    soft_limit = getattr(settings, "CELERY_TASK_SOFT_TIME_LIMIT", 540)
    assert actual_ttl >= soft_limit, (
        f"Lock TTL {actual_ttl}s < CELERY_TASK_SOFT_TIME_LIMIT {soft_limit}s; "
        "lock expires mid-cycle allowing overlapping ticks to double-publish."
    )


@pytest.mark.django_db
def test_process_retries_atomic_claim_prevents_double_publish(monkeypatch):
    """_process_retries must use an atomic status-flip (UPDATE WHERE status=SCHEDULED)
    so that two concurrent cycles cannot both claim and publish the same retry row.

    The test drives the engine with a PlatformPost already in PUBLISHING state
    (simulating a concurrent cycle that just claimed it) and verifies our cycle
    does NOT call _publish_platform_post for that row.
    """
    from apps.publisher.engine import PublishEngine
    from apps.composer.models import PlatformPost
    from django.utils import timezone

    publish_calls = []

    engine = PublishEngine.__new__(PublishEngine)

    # Patch _publish_platform_post to record calls.
    def fake_publish(pp):
        publish_calls.append(pp.pk)
        return {"success": True}

    monkeypatch.setattr(engine, "_publish_platform_post", fake_publish)
    monkeypatch.setattr(engine, "_sync_parent_published_at", lambda post: None)

    # Build a fake queryset of one PlatformPost already in PUBLISHING status.
    class FakePP:
        pk = 999
        id = 999
        status = PlatformPost.Status.PUBLISHING
        retry_count = 1

        class post:
            pass

    # Patch objects.filter so the atomic UPDATE returns 0 (already claimed).
    class FakeQS:
        def filter(self, **kwargs):
            return self

        def update(self, **kwargs):
            # Return 0 rows updated — another cycle already claimed this row.
            return 0

        def select_related(self, *args):
            return [FakePP()]

        def __iter__(self):
            return iter([FakePP()])

    original_filter = PlatformPost.objects.filter

    def patched_filter(**kwargs):
        # Only intercept the atomic-update inner filter call.
        if set(kwargs.keys()) == {"status", "id"}:
            return FakeQS()
        return original_filter(**kwargs)

    monkeypatch.setattr(PlatformPost.objects, "filter", patched_filter)

    # Build the outer queryset that _process_retries iterates.
    class OuterQS:
        def filter(self, **kwargs):
            return self

        def select_related(self, *args):
            return self

        def __iter__(self):
            return iter([FakePP()])

    # Patch the outer filter too so we control what posts are returned.
    call_count = [0]

    def multi_filter(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: outer query returning one "due retry" row.
            return OuterQS()
        # Subsequent calls: atomic claim inner filter.
        return FakeQS()

    monkeypatch.setattr(PlatformPost.objects, "filter", multi_filter)

    engine._process_retries()

    assert publish_calls == [], (
        "_publish_platform_post was called even though the atomic claim returned 0 rows; "
        "double-publish race condition not fixed."
    )
