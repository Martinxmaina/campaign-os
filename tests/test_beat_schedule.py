from django.conf import settings


def test_beat_schedule_is_wired():
    assert settings.CELERY_BEAT_SCHEDULE is not None


def test_every_beat_entry_resolves_to_a_real_task():
    """Each scheduled 'task' must be REGISTERED with the worker.

    We assert against the live ``app.tasks`` registry rather than merely
    importing the dotted path's module. Importing the module proves the
    path exists; it does NOT prove the worker (which registers tasks via
    ``autodiscover_tasks`` over INSTALLED_APPS) ever loaded it. The latter
    is the property beat actually depends on, and the gap is exactly what
    let the jobs.tasks.beat_heartbeat registration bug ship green.
    """
    from config.celery import app
    # force autodiscovery so registered task names are populated
    app.loader.import_default_modules()
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        dotted = entry["task"]
        assert dotted in app.tasks, f"{name}: {dotted} not registered with worker"
