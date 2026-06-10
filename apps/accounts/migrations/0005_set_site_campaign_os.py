from django.db import migrations


def set_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.update_or_create(
        id=1,
        defaults={"domain": "app.waiis.org", "name": "WAIIS Dispatch"},
    )


def revert_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(id=1).update(domain="studio.brightbean.xyz", name="Brightbean")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_set_site_brightbean"),
    ]
    operations = [migrations.RunPython(set_site, revert_site)]
