# Generated migration: add Blotato add-on family to PlatformCredential.Platform choices.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('credentials', '0005_alter_platformcredential_platform'),
    ]

    operations = [
        migrations.AlterField(
            model_name='platformcredential',
            name='platform',
            field=models.CharField(
                choices=[
                    ('facebook', 'Facebook'),
                    ('instagram', 'Instagram'),
                    ('instagram_login', 'Instagram (Direct)'),
                    ('linkedin_personal', 'LinkedIn (Personal Profile)'),
                    ('linkedin_company', 'LinkedIn (Company Page)'),
                    ('tiktok', 'TikTok'),
                    ('youtube', 'YouTube'),
                    ('pinterest', 'Pinterest'),
                    ('threads', 'Threads'),
                    ('bluesky', 'Bluesky'),
                    ('google_business', 'Google Business Profile'),
                    ('mastodon', 'Mastodon'),
                    ('ghost', 'Ghost (Nexus Brief)'),
                    ('blotato_instagram', 'Instagram (Blotato)'),
                    ('blotato_facebook', 'Facebook (Blotato)'),
                    ('blotato_twitter', 'X / Twitter (Blotato)'),
                    ('blotato_linkedin', 'LinkedIn (Blotato)'),
                    ('blotato_threads', 'Threads (Blotato)'),
                    ('blotato_bluesky', 'Bluesky (Blotato)'),
                ],
                max_length=30,
            ),
        ),
    ]
