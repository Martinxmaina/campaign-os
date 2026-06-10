# Campaign OS — CLAUDE.md

## App Map

| App | Purpose |
|-----|---------|
| apps/accounts | Custom User model, Django-allauth social login |
| apps/organizations | Org + workspace hierarchy (one Org → N Workspaces/houses) |
| apps/workspaces | Workspace model (= "house": WAIIS, AfCEN, etc.) |
| apps/members | OrgMembership + WorkspaceMembership + RBAC (campaign_owner/principal/pillar_lead/member) |
| apps/composer | Post, PlatformPost, Idea, Feed models; composer UI |
| apps/content_intake | ContentIntake from Google Sheets; normalization; intake board |
| apps/publisher | Engine: gate→dispatch to social providers; PublishLog; retry |
| apps/approvals | ApprovalAction, PostComment; approval workflow |
| apps/calendar | Calendar view; scheduled slots |
| apps/analytics | Post analytics sync from platforms |
| apps/social_accounts | SocialAccount (OAuth tokens per platform) |
| apps/intelligence | IntelligenceSubscription; agent-service HTTP client |
| apps/media_library | MediaAsset; S3/local storage |
| apps/notifications | In-app + email notifications |
| apps/inbox | Social inbox; reply management |
| apps/api | Django-Ninja API (Agent API); idempotency |
| apps/api_keys | API key issuance (prefix: cos_) |
| apps/evals | EvalCase + EvalRun for content agent QA |
| jobs/ | Celery tasks + beat schedules (single source of truth in jobs/schedules.py) |
| providers/ | Social platform publish adapters (LinkedIn, Meta, X, YouTube, Threads, Mock) |
| config/ | Django settings (base/dev/prod/test), Celery, URLs |

## Key Invariants

- Gate is authoritative at apps/publisher/engine._dispatch_to_provider (covers fresh + retry + first-comment).
- Content hash is text-only (caption + first_comment); PATCH clears gate_id/content_hash.
- Beat schedules live ONLY in jobs/schedules.py — no app.ready() registration.
- Cross-house wall: ContentIntake items are workspace-scoped; Posts reference intake from same workspace only.
- Sensitivity fail-closed: unrecognized strings → private_hold + IntakeReviewItem (never silent drop).
- Unblock conditions block scheduling at model level (ContentIntake.is_schedulable property).
- Agent API keys use prefix cos_ (not bb_studio_).

## Running tests
```bash
uv run pytest -x -q
```

## Migrations
```bash
uv run python manage.py makemigrations
uv run python manage.py migrate
```

## Sheets sync
Reads from CONTENT_INTAKE_SHEET_ID env var. Beat task: apps.content_intake.tasks.sync_all_intake_sheets (15-min).
