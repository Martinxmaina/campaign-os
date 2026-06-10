"""Single source of truth for all Celery beat schedules in Campaign OS.

Every periodic job is declared here — app ``ready()`` hooks must NOT
register recurring work. Entries are filled in as tasks are migrated
(Tasks 4-9). ``task`` values are dotted paths to @shared_task functions.
"""
from celery.schedules import schedule

BEAT_SCHEDULE: dict = {
    # filled in by later tasks
}
