# Phase 1 Gap Audit — Campaign OS

> Generated: 2026-06-10  
> Branch: feature/phase1-c1-herald  
> Purpose: Document every gap between the current BrightBean-fork baseline and
> the full Campaign OS feature set before Part A work begins.

---

## Rebrand gaps

The following files still carry upstream BrightBean strings that must be
replaced with Campaign OS branding in Task 2.

### Python source

| File | String(s) |
|------|-----------|
| `apps/api_keys/models.py:31` | Token format docstring references `bb_studio_<random32>_<lookup8>` |
| `apps/api_keys/services.py:34` | `TOKEN_PREFIX = "bb_studio_"` |
| `apps/api_keys/services.py:64` | HMAC info string `b"brightbean-api-key-hmac"` |
| `apps/common/encryption.py:37` | Encryption context string `b"brightbean-field-encryption"` |
| `apps/mcp/protocol.py:33` | `SERVER_NAME = "brightbean-studio"` |
| `apps/mcp/transport.py:5` | Docstring references `Authorization: Bearer bb_studio_...` |
| `apps/api/auth.py:3` | Docstring references `Bearer bb_studio_…` header |
| `apps/media_library/services.py:302` | Temp-file prefix `brightbean_thumb_` |
| `apps/social_accounts/management/commands/instagram_review_test_calls.py:25-26` | `DEFAULT_CAPTION` and `DEFAULT_COMMENT` strings contain "BrightBean App Review" |
| `apps/composer/curated_feeds.py:11,54` | Feed slug `brightbean-favorites` and label `Brightbean Favorites` |
| `apps/composer/views.py:3042,3137` | Default category fallback `"brightbean-favorites"` |
| `config/settings/base.py:17` | `SOURCE_REPO_URL` env default points to `brightbeanxyz/brightbean-studio` |
| `config/settings/base.py:144` | Default `DATABASE_URL` DB name `brightbean` |
| `config/settings/test.py:43` | Test DB name `brightbean_test` |

### HTML templates

| File | String(s) |
|------|-----------|
| `templates/about.html:12-13` | "BrightBean Studio" attribution paragraph + GitHub link |
| `templates/intelligence/_finalizing_failed.html:3` | `support@brightbean.xyz` support email |
| `templates/intelligence/activation_failed.html:44-45` | `support@brightbean.xyz` |
| `templates/intelligence/activation_org_mismatch.html:12` | `support@brightbean.xyz` |
| `templates/intelligence/deployment_not_authorized.html:12` | `support@brightbean.xyz` |
| `templates/intelligence/_overlay_provisioning_failed.html:9` | `support@brightbean.xyz` |
| `templates/intelligence/_finalizing_unauthorized.html:4` | `support@brightbean.xyz` |
| `templates/account/login.html:24` | `img/brightbean-studio-logo.webp` static asset ref |
| `templates/account/signup.html:24` | `img/brightbean-studio-logo.webp` static asset ref |
| `templates/account/signup.html:119,121` | Links to `brightbean.xyz/terms-of-service/` and `brightbean.xyz/privacy-policy/` |
| `templates/account/accept_terms.html:21` | `img/brightbean-studio-logo.webp` static asset ref |
| `templates/account/accept_terms.html:58,60` | Links to `brightbean.xyz/terms-of-service/` and `brightbean.xyz/privacy-policy/` |

### Tests (update in lock-step with source)

| File | String(s) |
|------|-----------|
| `apps/api_keys/tests/test_views.py:290,313,319,328` | Assertions on `"bb_studio_"` prefix |
| `apps/api_keys/tests/test_services.py:151,160,162,165` | Assertions on `"bb_studio_"` prefix |
| `apps/mcp/tests/test_transport.py:181` | Assertion `serverInfo.name == "brightbean-studio"` |
| `apps/api/tests/test_routers.py:591` | Test token `bb_studio_fake-token-...` |

---

## RBAC gaps

`WorkspaceMembership.WorkspaceRole` currently defines six generic roles:

```
OWNER | MANAGER | EDITOR | CONTRIBUTOR | CLIENT | VIEWER
```

`OrgMembership.OrgRole` defines:

```
OWNER | ADMIN | MEMBER
```

Neither model has Campaign OS-specific roles. The following roles are needed
for the 21-day EGM campaign workflow (Task 3):

| Missing role | Where needed | Purpose |
|---|---|---|
| `campaign_owner` | `WorkspaceMembership` | End-to-end accountability for a campaign; can approve and publish without a second gate |
| `principal` | `WorkspaceMembership` | Joseph-class principal — content authored under this role triggers the Joseph-personal channel gate (Task 12) |
| `pillar_lead` | `WorkspaceMembership` | Owns one content pillar (Climate / Energy / AI / Governance); only reviews/approves posts in their pillar |

Until these roles exist, the channel-routing logic (Task 12), the agent
context builder (Task 10), and the intake review assignment (Task 9) cannot
be implemented correctly.

---

## Content Intake gaps (TA.1 work — Tasks 5-9)

No `ContentIntake`, `UnblockCondition`, or `IntakeReviewItem` model exists
anywhere in `apps/`. The entire intake surface is absent:

- No `ContentIntake` model to store incoming briefs from Google Sheets or
  manual entry (title, pillar, sensitivity level, scheduled week, status).
- No `UnblockCondition` model to record what must be resolved before a
  sensitive post can proceed (e.g. "await Joseph sign-off", "embargo lifts
  at date X").
- No `IntakeReviewItem` link table for assigning intake rows to pillar leads.
- No Google Sheets sync task — there is no 15-minute Celery beat entry for
  pulling the campaign content calendar from Sheets into `ContentIntake`.
- No intake board view or HTMX condition-close endpoint.
- The `apps/composer/models.py` `Post.Status.TODO` choice exists but is
  unused; no workflow connects it to intake state.

---

## Gate enforcement gaps (TA.2 work — Task 8)

The existing gate at the publisher chokepoint (`apps/publisher/engine.py`)
checks only:

1. `gate_id` presence on the `PlatformPost`
2. `verdict == "pass"` from the agent-service `/gate/verify/{id}` endpoint
3. `content_hash` match

It does **not** check:

- `ContentIntake.sensitivity` — high-sensitivity posts require human
  sign-off even after the AI gate passes.
- `UnblockCondition` rows — a post whose unblock condition has not been
  closed must be held regardless of gate verdict.
- `campaign_owner` / `principal` role check — the Joseph-personal channel
  (Task 12) must gate on whether the workspace contains a `principal`-role
  member who has explicitly approved.

Until Task 8 adds these checks, sensitive or embargoed content can reach the
publisher and be dispatched.

---

## Already done (no action needed)

| Capability | Location | Status |
|---|---|---|
| Redis cache | `config/settings/base.py:131` — `django.core.cache.backends.redis.RedisCache` | Live |
| Celery broker + result backend | `config/celery.py` — `campaign_os` app, Redis URL | Live |
| Celery Beat heartbeat | `jobs/schedules.py` — `beat-heartbeat` every 60 s | Live |
| Celery Beat publish cycle | `jobs/schedules.py` — `publish-cycle` every 15 s | Live |
| X / Twitter provider | `providers/twitter.py` — X API v2 manage-Tweets, OAuth2 user-context | Live (text; media upload deferred until creds available) |
| Approval gate chokepoint | `apps/publisher/engine.py:194-198` — every `PlatformPost` blocked before dispatch | Live |
| HMAC gate-verify client | `apps/publisher/gate_client.py` | Live |
| Agent-service gate endpoint | `agent-service /gate/verify/{id}` | Live (deployed to Railway) |
