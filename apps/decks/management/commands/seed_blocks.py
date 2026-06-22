"""Seed a realistic AfCEN deck block library (TB.5 Task 1).

Lays down the named AfCEN anchors the deck assembly engine assembles from —
Mission 300, Rockefeller catalytic capital, GEAPP energy-compute, GIZ digital
public infrastructure — plus a deliberately *unconfirmed* SE4ALL TA stat so the
assembly engine's "required slot, no confirmed block" guard (Task 2) has a real
fixture to fail on.

Idempotent: every block has a stable ``seed_key`` and is upserted with
``update_or_create``, so re-running the command never duplicates rows. Assign an
owner with ``--owner <email>`` (default: first owner-role user, else any user).

Run in prod via the public DB proxy (see reference-railway-oneoff-internal-db).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.decks.models import Block

# (seed_key, type, track, audience_type, sensitivity, confirmation_status, content_md, source_ref)
BLOCKS = [
    (
        "claim_mission300",
        Block.Type.CLAIM,
        ["core", "ai10bn"],
        Block.Audience.PHILANTHROPY_ANCHOR,
        Block.Sensitivity.PUBLIC_SAFE,
        Block.Confirmation.CONFIRMED,
        "Mission 300 aims to connect 300 million Africans to electricity by 2030 — "
        "the largest energy-access push in the continent's history, and the platform "
        "AfCEN is building the AI and digital layer on top of.",
        "wiki:mission-300",
    ),
    (
        "pillar_rockefeller_catalytic",
        Block.Type.PILLAR_DESCRIPTION,
        "ai10bn",
        Block.Audience.PHILANTHROPY_ANCHOR,
        Block.Sensitivity.PUBLIC_SAFE,
        Block.Confirmation.CONFIRMED,
        "Catalytic capital — patient, risk-tolerant philanthropic funding — is the "
        "wedge that crowds in the commercial and concessional finance behind it. AfCEN "
        "positions Rockefeller's catalytic capital as the first-loss layer that de-risks "
        "African-owned AI and energy infrastructure.",
        "wiki:catalytic-capital",
    ),
    (
        "case_geapp_energy_compute",
        Block.Type.CASE_STUDY,
        "ai10bn",
        Block.Audience.PHILANTHROPY_ANCHOR,
        Block.Sensitivity.PUBLIC_SAFE,
        Block.Confirmation.CONFIRMED,
        "The energy-compute nexus: GEAPP's distributed renewable build-out is the power "
        "spine for African data centres and edge compute. AfCEN's partnership pairs every "
        "megawatt of clean power with the compute and skills that turn it into an AI economy.",
        "wiki:geapp-energy-compute",
    ),
    (
        "pillar_giz_dpi",
        Block.Type.PILLAR_DESCRIPTION,
        ["programs", "core"],
        Block.Audience.BILATERAL_TA,
        Block.Sensitivity.PUBLIC_SAFE,
        Block.Confirmation.CONFIRMED,
        "Digital public infrastructure (DPI) — interoperable identity, payments and data "
        "exchange — is the rails the AI decade runs on. AfCEN's technical-assistance work "
        "with GIZ builds African-owned DPI as a public good, not a rented dependency.",
        "wiki:giz-dpi",
    ),
    (
        "stat_se4all_ta",
        Block.Type.STAT,
        ["programs", "core"],
        Block.Audience.BILATERAL_TA,
        Block.Sensitivity.PARTNER_ONLY,
        # Deliberately unconfirmed — the figure is sourced from a draft SE4ALL note and
        # must be verified before it can land on any slide (Task 2 fails on this).
        Block.Confirmation.UNCONFIRMED,
        "SE4ALL technical-assistance financing for the region is estimated at "
        "US$2.4bn over the next three years (draft figure — pending verification).",
        None,
    ),
    (
        "ask_dfi_blended",
        Block.Type.ASK,
        "ai10bn",
        Block.Audience.DFI,
        Block.Sensitivity.PARTNER_ONLY,
        Block.Confirmation.CONFIRMED,
        "The ask: anchor the blended-finance architecture with a senior commitment that "
        "unlocks the catalytic and concessional layers behind it.",
        "wiki:blended-finance",
    ),
    (
        "governance_afcen",
        Block.Type.GOVERNANCE,
        ["core", "programs", "ai10bn", "waiis"],
        Block.Audience.DFI,
        Block.Sensitivity.PUBLIC_SAFE,
        Block.Confirmation.CONFIRMED,
        "AfCEN is governed by an independent board with audited financials and a "
        "transparent grants-and-disbursement process — the fiduciary spine DFIs require.",
        "wiki:afcen-governance",
    ),
    (
        "closing_afcen",
        Block.Type.CLOSING,
        ["core", "programs", "ai10bn", "waiis"],
        Block.Audience.PHILANTHROPY_ANCHOR,
        Block.Sensitivity.PUBLIC_SAFE,
        Block.Confirmation.CONFIRMED,
        "Africa will not be a footnote in the AI decade. Partner with AfCEN to fund the "
        "builders, the compute and the power that are already here.",
        "wiki:afcen-vision",
    ),
]


class Command(BaseCommand):
    help = "Seed a realistic AfCEN deck block library (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--owner", default="", help="email of the user to own seeded blocks")

    def handle(self, *args, **opts):
        from apps.accounts.models import User

        owner = (
            User.objects.filter(email=opts["owner"]).first()
            if opts["owner"]
            else User.objects.filter(workspace_memberships__workspace_role="owner").first()
            or User.objects.first()
        )
        if owner is None:
            self.stderr.write("No user to own blocks — create a user first.")
            return

        created = updated = 0
        for seed_key, type_, track, audience, sensitivity, status, content_md, source_ref in BLOCKS:
            _, was_created = Block.objects.update_or_create(
                seed_key=seed_key,
                defaults=dict(
                    type=type_,
                    track=track,
                    audience_type=audience,
                    sensitivity=sensitivity,
                    confirmation_status=status,
                    content_md=content_md,
                    source_ref=source_ref,
                    owner=owner,
                ),
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"seed_blocks: {created} created, {updated} updated "
                f"({Block.objects.count()} total, owner={owner.email})"
            )
        )
