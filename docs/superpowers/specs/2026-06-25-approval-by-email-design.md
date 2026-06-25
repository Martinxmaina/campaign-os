# Approval-by-email flow — design

**Date:** 2026-06-25
**Status:** Approved (build directed); defaults locked
**Surface:** `apps/approvals` (+ `apps/composer` entry, `integrations/gmail`, `apps/settings_manager`)

## Goal

Let a publisher assign a person to review a post **before** it publishes. The reviewer gets an email with a **platform-styled preview**, and **approves or declines with a reason** (recorded) via secure no-login links. On approval, the publisher receives an **email with a "Publish now" button**; clicking it publishes through the **unchanged compliance gate**. The existing one-click Send stays as a separate path.

## Locked decisions
- **Action mechanism:** DB-backed, single-use, expiring tokens + public (no-login) review/publish pages.
- **Both flows kept:** this assign→approve→publish flow is added *alongside* the shipped one-click Send.
- **Preview:** email-safe HTML **card per target platform** (LinkedIn / X / Instagram / etc.), one per `PlatformPost`.
- **Reason:** required on **decline**, optional on **approve**. Recorded as an `ApprovalAction` (existing audit trail) + on the assignment.
- **Email transport:** a single `send_email` seam prefers the existing **Gmail-OAuth** sender (`integrations/gmail`), falls back to Django SMTP/console; sending is **non-fatal** (a transport failure never blocks the state change). Real prod email requires a `gmail.send`-scoped token (go-live input).
- **Gate:** publishing always runs the existing gated path (`schedule_now` → `_dispatch_to_provider`). Tokens never bypass the gate.

## Roles & state machine
- **Reviewer:** any email address; need not be a platform user.
- **Publisher:** the assigner (you).
- `Post.review_state`: `NONE → PENDING (assigned) → APPROVED → (published)`, or `→ CHANGES_REQUESTED` on decline.
- One-click Send remains a distinct path (reviewer approves+publishes in one click) — untouched.

## Data model (new, `apps/approvals/models.py`)
- **`ReviewAssignment`**: `post` (FK Post), `assigned_by` (FK user), `reviewer_email`, `reviewer_name` (blank ok), `status` (`PENDING|APPROVED|DECLINED|EXPIRED`, default PENDING), `reason` (TextField, blank), `decided_at` (nullable), `created_at`.
- **`ActionToken`**: `assignment` (FK ReviewAssignment), `purpose` (`REVIEW|PUBLISH`), `token` (CharField, random urlsafe, unique, indexed), `expires_at`, `used_at` (nullable). Single-use: a token with `used_at` set or past `expires_at` is invalid.
- Decisions also recorded via existing `ApprovalAction` (reason → its `comment`).

## Components (one responsibility each)
1. **`apps/approvals/tokens.py`** — `mint_token(assignment, purpose, ttl_days)` → ActionToken; `resolve_token(raw, purpose)` → ActionToken or None (checks unused + unexpired); `consume(token)` sets `used_at`.
2. **`apps/approvals/platform_cards.py`** — `render_cards(post) -> str`: one email-safe HTML card per `PlatformPost`, styled per `social_account.platform` (linkedin/x/instagram/facebook/threads/default), showing caption, first media thumb, account handle, platform badge.
3. **`apps/approvals/emailer.py`** — `send_email(to, subject, html)`: try Gmail-OAuth (`integrations.gmail.build_gmail_service` from an admin `GoogleIntegration` with gmail.send scope) → else Django `EmailMultiAlternatives` (SMTP/console). Returns bool; never raises.
4. **`apps/approvals/assignment_service.py`** — `assign_for_review(post, assigned_by, reviewer_email, reviewer_name)`: create `ReviewAssignment` (sets review_state=PENDING) + REVIEW token, render review email (cards + Approve/Decline links), `send_email`.
5. **Public views (`apps/approvals/review_views.py`, no login):**
   - `GET /review/<token>/` → review page: platform cards + Approve / Decline(reason) form. Invalid/used/expired → "link no longer valid" page.
   - `POST /review/<token>/` → records decision: `ApprovalAction` + assignment.status/reason/decided_at; consume token. **Approve:** review_state=APPROVED, mint PUBLISH token, email publisher the "Publish now" link + cards. **Decline (reason required):** review_state=CHANGES_REQUESTED, email publisher the reason. Idempotent on used token.
   - `GET /review/publish/<token>/` → confirm page (cards + Publish button). `POST` → consume token, run gated publish (`schedule_now(post)`), show result.
6. **Entry UI** — an "Assign for review" control on the post (composer/approvals surface): email + name → calls `assign_for_review`.

## Security
- Tokens: 32+ bytes urlsafe random, unique, single-use, expiring (default 7 days; setting `review.token_ttl_days`). Public pages are token-gated only.
- Decline requires a non-empty reason (server-enforced).
- Publish token runs only the existing approved-publish path; the gate at `_dispatch_to_provider` stays authoritative — a gate-blocked post still does not publish.
- Used/expired/invalid tokens render a safe terminal page (no enumeration, no 500).

## Settings (`apps/settings_manager/defaults.py`)
- `review.token_ttl_days` = 7
- `review.copy_email` (existing) — also the default publisher recipient if `assigned_by` has no email.

## Testing
- tokens: mint/resolve/consume; expired + used rejected.
- assignment_service: creates assignment + REVIEW token + sends one email; review_state=PENDING.
- review POST approve: ApprovalAction(APPROVED), assignment APPROVED, PUBLISH token minted, publisher emailed; review_state APPROVED.
- review POST decline without reason → 400/again; with reason → DECLINED + reason recorded + publisher emailed; review_state CHANGES_REQUESTED.
- publish token: runs schedule_now; **gate still authoritative** — a no-gate_id PlatformPost is NOT published (raises GateBlockError at dispatch); used token can't replay.
- platform_cards: one card per PlatformPost, contains platform badge + caption.
- emailer: Gmail path used when integration present; SMTP fallback when not; failure returns False (non-fatal).
- one-click Send path untouched (existing tests still green).

## Out of scope (YAGNI)
- No reviewer accounts/roles. No multi-reviewer quorum (one assignment at a time; re-assign replaces). No reply-to-email parsing. No change to the gate or publish engine.

## Go-live inputs (separate from build)
1. `gmail.send`-scoped Google refresh token (via `scripts/get_google_refresh_token.py`) so emails actually send; until then the seam falls back (no-op safe).
2. Blotato API key + per-account connect (workstream B) — unrelated to this flow's code.
