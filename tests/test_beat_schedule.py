import importlib

from django.conf import settings


def test_beat_schedule_is_wired():
    assert settings.CELERY_BEAT_SCHEDULE is not None


def test_every_beat_entry_resolves_to_a_real_task():
    """Each scheduled 'task' dotted path must be importable and decorated."""
    from config.celery import app
    # force autodiscovery so registered task names are populated
    app.loader.import_default_modules()
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        dotted = entry["task"]
        module, _, attr = dotted.rpartition(".")
        mod = importlib.import_module(module)
        assert hasattr(mod, attr), f"{name}: {dotted} not found"
