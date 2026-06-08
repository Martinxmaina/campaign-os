from django.db import migrations

# WAIIS is a single-tenant deployment: exactly one Organization ("AfCEN")
# and one default Workspace ("WAIIS"). The multi-org/workspace switcher UI
# is gone, so default create paths land everything here. This migration
# seeds that singleton idempotently.
DEFAULT_ORG_NAME = "AfCEN"
DEFAULT_WORKSPACE_NAME = "WAIIS"


def seed_singleton(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Workspace = apps.get_model("workspaces", "Workspace")

    org, _ = Organization.objects.get_or_create(
        name=DEFAULT_ORG_NAME,
        defaults={"default_timezone": "UTC"},
    )
    Workspace.objects.get_or_create(
        organization=org,
        name=DEFAULT_WORKSPACE_NAME,
        defaults={"description": "Default WAIIS workspace."},
    )


def unseed_singleton(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Workspace = apps.get_model("workspaces", "Workspace")
    Workspace.objects.filter(
        organization__name=DEFAULT_ORG_NAME, name=DEFAULT_WORKSPACE_NAME
    ).delete()
    Organization.objects.filter(name=DEFAULT_ORG_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_organization_billing_email"),
        ("workspaces", "0003_alter_workspace_primary_color_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_singleton, unseed_singleton),
    ]
