"""Single source of truth for all Celery beat schedules in Campaign OS.

Every periodic job is declared here — app ``ready()`` hooks must NOT
register recurring work. Entries are filled in as tasks are migrated
(Tasks 4-9). ``task`` values are dotted paths to @shared_task functions.
"""
from celery.schedules import schedule

BEAT_SCHEDULE: dict = {
    "sweep-stale-idempotency": {
        "task": "apps.api.tasks.sweep_stale_idempotency_records",
        "schedule": schedule(run_every=3600),  # hourly
    },
    "social-health-checks": {
        "task": "apps.social_accounts.tasks.schedule_all_health_checks",
        "schedule": schedule(run_every=6 * 3600),
    },
    "intelligence-reconcile": {
        "task": "apps.intelligence.tasks.reconcile_intelligence_subscriptions",
        "schedule": schedule(run_every=6 * 3600),
    },
    "publish-cycle": {
        "task": "apps.publisher.tasks.run_publish_cycle",
        "schedule": schedule(run_every=15),
    },
}
