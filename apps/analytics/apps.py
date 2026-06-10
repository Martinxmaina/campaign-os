import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analytics"
    verbose_name = "Analytics"

    def ready(self):
        # Connect the on-connect backfill signal. The hourly incremental
        # sync is scheduled by Celery beat (see jobs/schedules.py), not here.
        from . import signals  # noqa: F401
