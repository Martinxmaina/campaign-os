"""One-time migration: pull existing outreach threads from agent-service into
the canonical Django CRM (apps.crm).

This is the first strangler step — Django becomes the owner of CRM data while
agent-service keeps the dossier/wiki/gate intelligence. The command fetches
``GET /threads`` over the agent_client, and for each item:

  * ``get_or_create`` an Organization by name,
  * ``get_or_create`` a Contact by (org, email) — falling back to full_name,
  * ``update_or_create`` an OutreachThread keyed on ``agent_thread_id``,
    carrying stage/track/score/quintile/traffic_light/dossier_id.

Dedup: a pre-existing Organization/Contact (e.g. from a spreadsheet import) is
reused, never duplicated. The command is idempotent (re-running makes no new
rows) and supports ``--dry-run`` (parse + report, write nothing). Per-row
failures are collected into an error report and printed — never silently
dropped.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.common.agent_client import AgentClientError, agent_get
from apps.crm.models import Contact, Organization, OutreachThread


class Command(BaseCommand):
    help = "Import existing outreach threads from agent-service into apps.crm (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Parse and report counts without writing any rows.",
        )

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]

        try:
            data = agent_get("/threads") or {}
        except AgentClientError as exc:
            self.stderr.write(self.style.ERROR(f"agent-service unreachable: {exc}"))
            return

        items = data.get("items") or []
        created = updated = skipped = 0
        errors: list[tuple[str, str]] = []

        for item in items:
            agent_thread_id = str(item.get("id") or "").strip()
            if not agent_thread_id:
                errors.append(("<no-id>", "missing thread id"))
                continue

            org_name = (item.get("org") or "").strip()
            if not org_name:
                errors.append((agent_thread_id, "missing org name"))
                continue

            if dry_run:
                # Report what *would* happen without touching the DB.
                exists = OutreachThread.objects.filter(agent_thread_id=agent_thread_id).exists()
                if exists:
                    updated += 1
                else:
                    created += 1
                continue

            try:
                with transaction.atomic():
                    was_created = self._import_row(item, agent_thread_id, org_name)
                if was_created:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:  # never silently drop a row
                errors.append((agent_thread_id, str(exc)))
                skipped += 1

        verb = "Would import" if dry_run else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: created={created} updated={updated} skipped={skipped} "
                f"errors={len(errors)} (of {len(items)} threads)"
            )
        )
        if errors:
            self.stdout.write(self.style.WARNING("Per-row error report:"))
            for thread_id, reason in errors:
                self.stdout.write(f"  · {thread_id}: {reason}")

    def _import_row(self, item: dict, agent_thread_id: str, org_name: str) -> bool:
        """Create/update the org+contact+thread for one agent-service item.

        Returns True if the OutreachThread was created, False if updated.
        """
        # Organization — dedup by case-insensitive name.
        org = Organization.objects.filter(name__iexact=org_name).first()
        if org is None:
            org = Organization.objects.create(name=org_name)

        # Contact — dedup by (org, email) then (org, full_name).
        contact = None
        email = (item.get("contact_email") or "").strip()
        full_name = (item.get("contact_name") or "").strip()
        if email:
            contact = Contact.objects.filter(org=org, email__iexact=email).first()
        if contact is None and full_name:
            contact = Contact.objects.filter(org=org, full_name__iexact=full_name).first()
        if contact is None and (email or full_name):
            contact = Contact.objects.create(
                org=org, full_name=full_name, email=email
            )

        _, was_created = OutreachThread.objects.update_or_create(
            agent_thread_id=agent_thread_id,
            defaults={
                "org": org,
                "primary_contact": contact,
                "stage": item.get("stage") or OutreachThread.Stage.TARGETED,
                "track": item.get("track") or "",
                "score": float(item.get("score") or 0.0),
                "quintile": int(item.get("quintile") or 0),
                "traffic_light": item.get("traffic_light") or "green",
                "dossier_id": item.get("dossier_id") or "",
                "sector": item.get("sector") or "",
                "pillar": item.get("pillar") or "",
            },
        )
        return was_created
