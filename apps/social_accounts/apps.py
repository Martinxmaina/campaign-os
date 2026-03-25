from django.apps import AppConfig


class SocialAccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.social_accounts"
    verbose_name = "Social Accounts"

    def ready(self):
        # Register the recurring health-check task.
        # django-background-tasks deduplicates by verbose_name so this
        # is safe to call on every startup — it will not create duplicates.
        from background_task.models import Task

        from .tasks import schedule_all_health_checks

        # Only schedule if no pending task with this name exists
        if not Task.objects.filter(verbose_name="schedule_all_health_checks").exists():
            # Run every 6 hours (repeat=Task.DAILY would be 24h;
            # we use repeat=6*3600 for more frequent checks).
            schedule_all_health_checks(
                repeat=6 * 3600,
                verbose_name="schedule_all_health_checks",
            )
