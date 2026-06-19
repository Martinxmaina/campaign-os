"""Single source of truth for all Celery beat schedules in Campaign OS.

Every periodic job is declared here — app ``ready()`` hooks must NOT
register recurring work. Entries are filled in as tasks are migrated
(Tasks 4-9). ``task`` values are dotted paths to @shared_task functions.
"""
from celery.schedules import schedule

BEAT_SCHEDULE: dict = {
    "sweep-stale-idempotency": {
        "task": "apps.api.tasks.sweep_stale_idempotency_records",
        "schedule": schedule(run_every=3600),  # hourly
    },
    "social-health-checks": {
        "task": "apps.social_accounts.tasks.schedule_all_health_checks",
        "schedule": schedule(run_every=6 * 3600),
    },
    "intelligence-reconcile": {
        "task": "apps.intelligence.tasks.reconcile_intelligence_subscriptions",
        "schedule": schedule(run_every=6 * 3600),
    },
    "analytics-sync": {
        "task": "apps.analytics.tasks.sync_all_account_analytics",
        "schedule": schedule(run_every=3600),  # hourly
    },
    "crm-sheet-mirror": {
        "task": "apps.crm.tasks.mirror_crm_tracker",
        "schedule": schedule(run_every=24 * 3600),  # daily — mirror CRM pipeline → tracker sheet
    },
    "publish-cycle": {
        "task": "apps.publisher.tasks.run_publish_cycle",
        "schedule": schedule(run_every=15),
    },
    "beat-heartbeat": {
        "task": "jobs.tasks.beat_heartbeat",
        "schedule": schedule(run_every=60),
    },
    "sweep-scheduled-org-deletions": {
        # Durability net for the 14-day grace-period deletion flow.
        # The eta-enqueued Celery message lives only in Redis; a broker
        # restart without persistence would silently strand orgs in
        # 'pending deletion'.  This daily sweep re-uses the idempotent
        # execute_scheduled_org_deletion body via a dedicated sweep task
        # so any missed eta fires are caught within 24 h at most.
        "task": "apps.organizations.tasks.sweep_scheduled_org_deletions",
        "schedule": schedule(run_every=86400),  # daily
    },
    "sweep-stale-pending-activations": {
        # Durability net for the paid-activation worker path.
        # provision_intelligence_account_via_session is enqueued as a
        # Redis-only Celery message; a broker restart / eviction during
        # the up-to-1 h countdown window silently strands the
        # PendingActivation row in PENDING forever.  This hourly sweep
        # re-enqueues any PENDING/IN_PROGRESS row not updated within 2 h.
        # The worker is idempotent and status-gated, so double-delivery
        # is safe.  Consistent with sweep_scheduled_org_deletions pattern.
        "task": "apps.intelligence.tasks.sweep_stale_pending_activations",
        "schedule": schedule(run_every=3600),  # hourly
    },
    "intake-sheets-sync": {
        # Pull content-planning register from Google Sheets every 15 minutes.
        # No-ops when CONTENT_INTAKE_SHEET_ID is not configured.
        "task": "apps.content_intake.tasks.sync_all_intake_sheets",
        "schedule": schedule(run_every=900),  # 15 min
    },
    "calendar-gap-scan": {
        # Daily 14-day gap scanner — proposes fill-in dates across all workspaces.
        "task": "apps.content_intake.tasks.run_calendar_gap_scan",
        "schedule": schedule(run_every=86400),  # daily
    },
    "joseph-calendar-sync": {
        # Pull each member's upcoming Google Calendar events every 5 minutes and
        # fuzzy-link them to threads. No-ops when no GoogleIntegration exists, so
        # it is safe to run before Joseph's OAuth re-consent.
        "task": "apps.joseph.tasks.sync_google_calendar",
        "schedule": schedule(run_every=300),  # 5 min
    },
    "joseph-meeting-prep": {
        # Pre-meeting cascade T-5/T-2/T-0: refresh dossier, draft + gate talking
        # points, mark the brief ready. Idempotent via CalendarEvent.prep_stages,
        # so a 30-min cadence is safe. No-ops when no linked future events exist.
        "task": "apps.joseph.tasks.run_meeting_prep",
        "schedule": schedule(run_every=1800),  # 30 min
    },
    "joseph-gmail-sync": {
        # Pull each member's recent inbound Gmail every 10 minutes and POST it to
        # agent-service /ingest (source_type=email_inbound). No-ops when no
        # GoogleIntegration exists, so it is safe to run before OAuth re-consent.
        "task": "apps.joseph.tasks.sync_google_gmail",
        "schedule": schedule(run_every=600),  # 10 min
    },
    "crm-score-threads": {
        # DEAL-ENGINE scoring ported to Django (CRM is now canonical). Recompute
        # score/quintile/traffic_light for every open thread, once a day.
        "task": "apps.crm.tasks.score_all_threads",
        "schedule": schedule(run_every=86400),  # daily
    },
    "crm-no-reply": {
        # Flip traffic_light amber (>14d) / red (>28d) since last_touch on open
        # threads and stamp a follow-up next_action. Daily.
        "task": "apps.crm.tasks.flag_no_reply",
        "schedule": schedule(run_every=86400),  # daily
    },
    "outreach-advance": {
        # Advance multi-step outreach sequences: gate+send due email steps and
        # open owner tasks for due human-channel steps (linkedin/whatsapp/call).
        # Every outbound email goes through the gate inside send_email. Daily.
        "task": "apps.outreach.tasks.advance_sequences",
        "schedule": schedule(run_every=86400),  # daily
    },
    "outreach-no-reply": {
        # Draft follow-ups for sent outreach email steps that have gone
        # unanswered: open an owner Task + flip traffic_light amber (>=14d) /
        # red (>=28d). Never auto-sends — the owner sends through the gate. Daily.
        "task": "apps.outreach.tasks.run_no_reply_followups",
        "schedule": schedule(run_every=86400),  # daily
    },
}
