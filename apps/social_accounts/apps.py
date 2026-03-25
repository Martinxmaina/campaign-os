import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class SocialAccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.social_accounts"
    verbose_name = "Social Accounts"

    def ready(self):
        # Register the recurring health-check task on startup.
        # Guarded with try/except so environments without a database
        # (e.g. mypy, collectstatic) don't crash.
        try:
            from background_task.models import Task

            from .tasks import schedule_all_health_checks

            if not Task.objects.filter(verbose_name="schedule_all_health_checks").exists():
                schedule_all_health_checks(
                    repeat=6 * 3600,
                    verbose_name="schedule_all_health_checks",
                )
        except Exception:
            logger.debug("Skipping health-check task registration (database not available)")
