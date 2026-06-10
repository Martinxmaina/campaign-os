# Generated migration for content_intake — spec-compliant initial state

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('composer', '0017_platformpost_content_hash_platformpost_gate_id'),
        ('workspaces', '0003_alter_workspace_primary_color_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentIntake',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('external_id', models.CharField(help_text='Row ID from Google Sheet', max_length=100)),
                ('row_hash', models.CharField(blank=True, default='', help_text='SHA-256 of raw row JSON', max_length=64)),
                ('submitted_by_raw', models.CharField(blank=True, default='', max_length=255)),
                ('pillar_theme', models.CharField(blank=True, default='', max_length=255)),
                ('angle', models.TextField(blank=True, default='')),
                ('proof_point', models.TextField(blank=True, default='')),
                ('proof_status', models.CharField(choices=[('confirmed', 'Confirmed'), ('tbd', 'TBD'), ('needs_verification', 'Needs Verification')], default='confirmed', max_length=30)),
                ('target_audience', models.TextField(blank=True, default='')),
                ('sensitivity', models.CharField(choices=[('public_safe', 'Public Safe'), ('partner_only', 'Partner Only'), ('private_hold', 'Private Hold'), ('confidential', 'Confidential')], db_index=True, default='private_hold', max_length=20)),
                ('channel_targets', models.JSONField(blank=True, default=list, help_text='Parsed channel targets: [{platform, account, flags}]')),
                ('campaign', models.CharField(blank=True, default='', max_length=255)),
                ('house', models.CharField(blank=True, default='', help_text='WAIIS | AfCEN | AI10Bn etc.', max_length=100)),
                ('priority', models.CharField(choices=[('H', 'High'), ('M', 'Medium'), ('L', 'Low')], default='M', max_length=1)),
                ('status', models.CharField(choices=[('idea', 'Idea'), ('accepted', 'Accepted'), ('drafting', 'Drafting'), ('in_review', 'In Review'), ('approved', 'Approved'), ('scheduled', 'Scheduled'), ('published', 'Published'), ('archived', 'Archived'), ('blocked', 'Blocked'), ('held', 'Held'), ('skipped', 'Skipped'), ('review_queue', 'Review Queue')], db_index=True, default='idea', max_length=20)),
                ('owner_raw', models.CharField(blank=True, default='', max_length=255)),
                ('target_publish_date', models.DateField(blank=True, null=True)),
                ('notes_raw', models.TextField(blank=True, default='')),
                ('reference_links', models.JSONField(blank=True, default=list)),
                ('skip_reason', models.CharField(blank=True, default='', max_length=255)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('sync_error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_intake_items', to=settings.AUTH_USER_MODEL)),
                ('post', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='intake_source', to='composer.post')),
                ('submitted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submitted_intake_items', to=settings.AUTH_USER_MODEL)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='intake_items', to='workspaces.workspace')),
            ],
            options={
                'db_table': 'content_intake_item',
                'ordering': ['-created_at'],
                'unique_together': {('workspace', 'external_id')},
                'indexes': [
                    models.Index(fields=['status', 'sensitivity'], name='idx_intake_status_sens'),
                    models.Index(fields=['workspace', 'priority'], name='idx_intake_ws_priority'),
                ],
            },
        ),
        migrations.CreateModel(
            name='IntakeReviewItem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('external_id', models.CharField(max_length=100)),
                ('raw_row', models.JSONField(help_text='Original row data from Sheets')),
                ('reason', models.CharField(choices=[('sensitivity_unrecognized', 'Sensitivity Unrecognized'), ('status_unmapped', 'Status Unmapped'), ('channel_unparseable', 'Channel Unparseable'), ('general_parse_failure', 'General Parse Failure')], max_length=40)),
                ('detail', models.TextField(blank=True, default='')),
                ('resolved', models.BooleanField(default=False)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='intake_review_items', to='workspaces.workspace')),
            ],
            options={
                'db_table': 'content_intake_review_item',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='UnblockCondition',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('condition_type', models.CharField(choices=[('source_verification', 'Source Verification'), ('partner_permission', 'Partner Permission'), ('legal_milestone', 'Legal Milestone'), ('figure_confirmation', 'Figure Confirmation')], max_length=30)),
                ('description', models.TextField()),
                ('owner_raw', models.CharField(blank=True, default='', max_length=255)),
                ('status', models.CharField(choices=[('open', 'Open'), ('closed', 'Closed')], default='open', max_length=10)),
                ('evidence_note', models.TextField(blank=True, default='')),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('closed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='closed_conditions', to=settings.AUTH_USER_MODEL)),
                ('intake', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='unblock_conditions', to='content_intake.contentintake')),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_conditions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'content_intake_unblock_condition',
                'ordering': ['created_at'],
            },
        ),
    ]
