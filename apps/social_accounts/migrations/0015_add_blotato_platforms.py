# Generated migration: add Blotato add-on family platform choices.

from django.db import migrations, models


_BLOTATO_CHOICES = [
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
]


class Migration(migrations.Migration):

    dependencies = [
        ('social_accounts', '0014_socialaccount_provider_config'),
        ('credentials', '0006_add_blotato_platforms'),
    ]

    operations = [
        migrations.AlterField(
            model_name='socialaccount',
            name='platform',
            field=models.CharField(choices=_BLOTATO_CHOICES, max_length=30),
        ),
        migrations.AlterField(
            model_name='analyticsplatformconfig',
            name='platform',
            field=models.CharField(choices=_BLOTATO_CHOICES, max_length=30, unique=True),
        ),
        migrations.AlterField(
            model_name='platformvisibility',
            name='platform',
            field=models.CharField(choices=_BLOTATO_CHOICES, max_length=30, unique=True),
        ),
    ]
