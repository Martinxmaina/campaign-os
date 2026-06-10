import contextlib

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
