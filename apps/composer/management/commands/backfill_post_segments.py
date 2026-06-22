"""Backfill track / pillar / campaign on existing Posts from their intake source.

For every Post linked to a ContentIntake (via the OneToOne ``intake_source``),
carry the plan row's segmentation onto the Post: pillar (normalized from
``pillar_theme`` via the sector map), campaign (copied), track (inferred when a
signal is present). Only fills fields that are still blank, so the command is
idempotent and never clobbers a value an editor already chose.

Run in prod via the public DB proxy (see reference-railway-oneoff-internal-db):
  railway run --service web -- bash -c "DATABASE_URL=$DATABASE_PUBLIC_URL \
    DJANGO_SETTINGS_MODULE=config.settings.production .venv/bin/python \
    manage.py backfill_post_segments"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.composer.models import Post
from apps.composer.segments import infer_track, normalize_pillar


class Command(BaseCommand):
    help = "Backfill track/pillar/campaign on existing Posts from their intake source (idempotent)."

    def handle(self, *args, **opts):
        updated = 0
        scanned = 0
        # Only Posts that actually have a linked intake row carry segmentation.
        posts = (
            Post.objects.exclude(intake_source__isnull=True)
            .select_related("intake_source")
        )
        for post in posts:
            scanned += 1
            intake = post.intake_source
            update_fields = []

            if not post.pillar:
                pillar = normalize_pillar(intake.pillar_theme)
                if pillar:
                    post.pillar = pillar
                    update_fields.append("pillar")

            if not post.campaign:
                campaign = (intake.campaign or "").strip()
                if campaign:
                    post.campaign = campaign
                    update_fields.append("campaign")

            if not post.track:
                track = infer_track(intake.campaign, intake.angle, intake.pillar_theme)
                if track:
                    post.track = track
                    update_fields.append("track")

            if update_fields:
                post.save(update_fields=update_fields)
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"backfilled {updated} of {scanned} intake-linked posts")
        )
