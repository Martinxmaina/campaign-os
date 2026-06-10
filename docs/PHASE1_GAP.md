# Phase 1 Gap Audit — Campaign OS

Generated: 2026-06-10

## Rebrand gaps (BrightBean strings remaining)
- `apps/api_keys/models.py` — key prefix `bb_studio_` → `cos_`
- `apps/api_keys/services.py` — prefix string
- `config/settings/base.py` — SOURCE_REPO_URL, default DATABASE_URL
- `apps/common/encryption.py` — BRIGHTBEAN_ENCRYPTION_KEY env var ref
- `apps/composer/curated_feeds.py` — user-agent header
- `apps/mcp/protocol.py` + `transport.py` — MCP server name
- `templates/account/login.html` + `signup.html` + `about.html` — display strings
- `templates/intelligence/*.html` — display strings

## Procrastinate
- Not installed; Celery+Redis already in place. No migration needed. ✅

## Redis + Celery
- Fully wired in base.py + config/celery.py + jobs/schedules.py. ✅

## Beat heartbeat
- `jobs/tasks.beat_heartbeat` registered in BEAT_SCHEDULE. ✅

## RBAC gaps
- `WorkspaceMembership.WorkspaceRole` has owner/manager/editor/contributor/client/viewer.
- Missing Campaign OS roles: `campaign_owner`, `principal`, `pillar_lead`.
- No pillar/house scoping at manager level (Task 3).

## Content Intake
- No model or Sheets sync yet (Task 4–9).

## Gate enforcement
- Gate exists at `publisher/engine.py _dispatch_to_provider`. 
- No sensitivity or unblock-conditions check (Task 10–12).

## Media/first_comment binding in gate hash
- Deferred from Phase 1. Implement in Task 10.

## X/Twitter derivation
- `providers/twitter.py` exists. Daily derive job not wired (Task 20).
