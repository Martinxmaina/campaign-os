"""Seed a realistic AfCEN demo dataset so every surface is walkable for testing.

Populates: funder Organizations (type/tier/track), Contacts, OutreachThreads spread
across stages with mixed traffic-lights/scores/next-actions, Activities (audit
timeline), Tasks, today/this-week CalendarEvents linked to threads (Today strip),
a SequenceTemplate + enrolled Sequences, and a Mailbox for the owner.

Idempotent (get_or_create on stable keys). ``--wipe`` removes the demo rows.
Assign to a real user with ``--owner <email>`` (default: first owner-role user).

Run in prod via the public DB proxy (see reference-railway-oneoff-internal-db):
  railway run --service web -- bash -c "DATABASE_URL=$DATABASE_PUBLIC_URL \
    DJANGO_SETTINGS_MODULE=config.settings.production .venv/bin/python \
    manage.py seed_demo --owner martin.maina@africacen.org"
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

# Curated demo funders. (name, type, tier, tracks, contact, role, seniority, email)
FUNDERS = [
    ("Rockefeller Foundation", "funder", "tier1_anchor", ["ai10bn", "core"],
     "Dr. Amina Okonkwo", "VP, Climate & Africa", "vp", "a.okonkwo@rockfound.example"),
    ("GEAPP", "funder", "tier1_anchor", ["ai10bn"],
     "James Mwangi", "Director, Energy Access", "director", "j.mwangi@geapp.example"),
    ("GIZ", "bilateral", "tier2_warm", ["programs", "core"],
     "Klaus Berger", "Head, Digital Programmes", "director", "k.berger@giz.example"),
    ("Schmidt Futures", "funder", "tier1_anchor", ["ai10bn"],
     "Sarah Chen", "Partner, AI Initiatives", "vp", "s.chen@schmidtfutures.example"),
    ("Gates Foundation", "funder", "tier1_anchor", ["core", "programs"],
     "David Otieno", "Senior Program Officer", "manager", "d.otieno@gatesfound.example"),
    ("Mastercard Foundation", "funder", "tier2_warm", ["core"],
     "Grace Adeyemi", "Director, Africa", "director", "g.adeyemi@mastercardfdn.example"),
    ("Ford Foundation", "funder", "tier2_warm", ["core"],
     "Michael Roberts", "Africa Regional Director", "director", "m.roberts@fordfound.example"),
    ("IKEA Foundation", "funder", "tier3_cold", ["programs"],
     "Lena Svensson", "Programme Manager", "manager", "l.svensson@ikeafound.example"),
]

# (funder_name, stage, traffic_light, score, quintile, next_action, due_in_days, warmth)
THREADS = [
    ("Rockefeller Foundation", "proposal_sent", "red", 0.71, 4, "Follow up on $1.5M anchor proposal", -3, "hot"),
    ("GEAPP", "in_discussion", "amber", 0.64, 4, "Confirm 22 June meeting agenda", 2, "warm"),
    ("Schmidt Futures", "engaged", "red", 0.58, 3, "Re-engage — silent 11 days", -1, "warm"),
    ("GIZ", "proposal_sent", "green", 0.55, 3, "Send revised TA scope", 5, "warm"),
    ("Gates Foundation", "engaged", "green", 0.49, 3, "Draft concept note", 7, "warm"),
    ("Mastercard Foundation", "targeted", "green", 0.38, 2, "Request intro via Ford", 10, "cold"),
    ("Ford Foundation", "committed", "green", 0.82, 5, "Schedule grants-committee call", 4, "hot"),
    ("IKEA Foundation", "targeted", "amber", 0.22, 1, "Qualify fit for programmes track", 14, "cold"),
]

_DEMO_TAG = "demo-seed"  # marker in Organization.notes for --wipe


class Command(BaseCommand):
    help = "Seed a realistic AfCEN demo dataset (idempotent; --wipe to remove)."

    def add_arguments(self, parser):
        parser.add_argument("--owner", default="", help="email of the user to own demo threads")
        parser.add_argument("--wipe", action="store_true", help="remove demo data instead of seeding")

    def handle(self, *args, **opts):
        from apps.accounts.models import User
        from apps.crm.models import Activity, Contact, Organization, OutreachThread, Task

        if opts["wipe"]:
            orgs = Organization.objects.filter(notes__contains=_DEMO_TAG)
            n = orgs.count()
            orgs.delete()  # cascades to contacts/threads/activities/tasks
            self.stdout.write(self.style.SUCCESS(f"wiped {n} demo orgs (+ cascaded)"))
            return

        owner = (
            User.objects.filter(email=opts["owner"]).first() if opts["owner"]
            else User.objects.filter(workspace_memberships__workspace_role="owner").first()
            or User.objects.first()
        )
        if owner is None:
            self.stderr.write("no user found to own demo data"); return
        now = timezone.now()

        org_by_name, thread_by_name = {}, {}
        for name, typ, tier, tracks, cname, role, sen, email in FUNDERS:
            org, _ = Organization.objects.get_or_create(
                name=name,
                defaults=dict(type=typ, tier=tier, track_tags=tracks,
                              website=f"https://{name.split()[0].lower()}.example",
                              notes=_DEMO_TAG),
            )
            # ensure tag + enrichment on pre-existing orgs (e.g. migrated wave-1)
            org.type, org.tier, org.track_tags = typ, tier, tracks
            if _DEMO_TAG not in (org.notes or ""):
                org.notes = ((org.notes or "") + " " + _DEMO_TAG).strip()
            org.save()
            org_by_name[name] = org
            contact, _ = Contact.objects.get_or_create(
                org=org, email=email,
                defaults=dict(full_name=cname, role=role, seniority=sen,
                              warmth_source="warm_intro", last_verified=now.date()),
            )

        for name, stage, light, score, quint, action, due_in, warmth in THREADS:
            org = org_by_name[name]
            contact = org.contacts.first()
            thread, _ = OutreachThread.objects.get_or_create(
                org=org, owner=owner,
                defaults=dict(primary_contact=contact, track=(org.track_tags or [""])[0]),
            )
            thread.primary_contact = contact
            thread.track = (org.track_tags or [""])[0]
            thread.stage, thread.traffic_light = stage, light
            thread.score, thread.quintile = score, quint
            thread.warmth = warmth
            thread.next_action = action
            thread.next_action_due = (now + timedelta(days=due_in)).date()
            thread.last_touch = now - timedelta(days=abs(due_in))
            thread.last_touch_channel = "email"
            thread.save()
            thread_by_name[name] = thread

            # activity timeline (idempotent: only seed if empty)
            if not thread.activities.exists():
                Activity.objects.create(thread=thread, activity_type="email_sent",
                                        actor_type="human", actor=owner,
                                        content_ref={"summary": f"Intro email to {contact.full_name}"})
                Activity.objects.create(thread=thread, activity_type="meeting",
                                        actor_type="human", actor=owner,
                                        content_ref={"summary": "Intro call — positive"})
                Activity.objects.create(thread=thread, activity_type="note",
                                        actor_type="agent", agent_name="ATLAS",
                                        content_ref={"summary": "Dossier refreshed — 7 sources"})

        # a couple of open tasks
        rock = thread_by_name.get("Rockefeller Foundation")
        if rock and not Task.objects.filter(thread=rock).exists():
            Task.objects.create(thread=rock, owner=owner, type="send_email", status="open",
                                due=(now + timedelta(days=1)).date(),
                                drafted_content="Follow-up to grants committee (drafted, in your voice).")
            Task.objects.create(thread=rock, owner=owner, type="review_deck", status="open",
                                due=(now + timedelta(days=2)).date())

        self._seed_calendar(owner, thread_by_name, now)
        self._seed_outreach(owner, thread_by_name, now)

        self.stdout.write(self.style.SUCCESS(
            f"seeded: {len(FUNDERS)} orgs, {len(THREADS)} threads (owner={owner.email}), "
            f"activities+tasks, calendar, a sequence, a mailbox."))

    def _seed_calendar(self, owner, threads, now):
        from apps.joseph.models import CalendarEvent
        ws_id = getattr(owner, "last_workspace_id", None)
        from apps.workspaces.models import Workspace
        ws = (Workspace.objects.filter(id=ws_id).first() if ws_id
              else Workspace.objects.filter(memberships__user=owner).first())
        if ws is None:
            return
        plan = [("Rockefeller Foundation", 3), ("GEAPP", 2)]  # (thread, hours-from-now today/soon)
        for name, hrs in plan:
            t = threads.get(name)
            if not t:
                continue
            CalendarEvent.objects.get_or_create(
                google_event_id=f"demo-{t.id}",
                defaults=dict(workspace=ws, title=f"{name} — funder meeting",
                              start=now + timedelta(hours=hrs),
                              end=now + timedelta(hours=hrs + 1),
                              attendees=[{"email": t.primary_contact.email if t.primary_contact else ""}],
                              linked_thread_id=str(t.id), briefing_status="briefed"),
            )

    def _seed_outreach(self, owner, threads, now):
        from apps.outreach.models import Mailbox, Sequence, SequenceStep, SequenceTemplate
        Mailbox.objects.get_or_create(
            user=owner, email=owner.email,
            defaults=dict(daily_cap=50, ramp_started_at=now - timedelta(days=21)),
        )
        tmpl, _ = SequenceTemplate.objects.get_or_create(
            name="Funder warm intro (demo)",
            defaults=dict(description="3-touch warm intro for tier-1 funders",
                          steps=[{"kind": "email", "delay_days": 0, "subject": "Introduction — AfCEN",
                                  "body": "Hi {first_name}, ..."},
                                 {"kind": "email", "delay_days": 4, "subject": "Quick follow-up",
                                  "body": "Following up ..."},
                                 {"kind": "call_task", "delay_days": 7, "subject": "Call",
                                  "body": "Call to advance."}]),
        )
        for name in ("GIZ", "Gates Foundation"):
            t = threads.get(name)
            if not t or Sequence.objects.filter(thread=t).exists():
                continue
            seq = Sequence.objects.create(template=tmpl, thread=t, status="active")
            for i, step in enumerate(tmpl.steps, start=1):
                SequenceStep.objects.create(
                    sequence=seq, position=i, kind=step["kind"], subject=step["subject"],
                    body=step["body"], delay_days=step["delay_days"],
                    scheduled_for=now + timedelta(days=step["delay_days"]),
                    status="sent" if i == 1 else "pending",
                )
