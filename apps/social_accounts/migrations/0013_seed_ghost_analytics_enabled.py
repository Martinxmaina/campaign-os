"""Seed an enabled ghost AnalyticsPlatformConfig row.

The original analytics seed (0010) ran *before* ghost was added to the
platform choices (0012), so no ghost row was ever created and
``enabled_platforms()`` silently excluded it. This makes Ghost analytics
enabled-by-default permanent (was patched manually in prod).

Idempotent: update_or_create so re-running on an existing DB is a no-op.
"""

from django.db import migrations


def seed_ghost_analytics(apps, schema_editor):
    AnalyticsPlatformConfig = apps.get_model("social_accounts", "AnalyticsPlatformConfig")
    AnalyticsPlatformConfig.objects.update_or_create(
        platform="ghost",
        defaults={"is_enabled": True},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("social_accounts", "0012_alter_analyticsplatformconfig_platform_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_ghost_analytics, migrations.RunPython.noop),
    ]
