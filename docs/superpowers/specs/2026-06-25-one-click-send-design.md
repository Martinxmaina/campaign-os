# One-click "Send" — review → approve + email-copy + publish

**Date:** 2026-06-25
**Status:** Design approved (Approach A), pending implementation plan
**Surface:** `apps/approvals` (+ small touches to `apps/composer`, `apps/notifications`, `apps/settings_manager`)

## Goal

A user creates a post and assigns a reviewer. The reviewer opens it and clicks a single **Send** button. That one action:

1. **Approves** the post (records the sign-off in the audit trail),
2. **Emails a copy** of the post to a configured fixed inbox, and
3. **Publishes** it through the existing compliance gate.

No separate Approve-then-Publish steps. The gate stays authoritative — Send never bypasses it.

## What already exists (reused, not rebuilt)

- **Post review state machine** — `apps/composer/models.py::Post`: `review_state` (`NONE|PENDING|APPROVED|CHANGES_REQUESTED|REJECTED`), `review_assignee`, `author`.
- **Reviewer assignment** — `apps/composer/studio_views.py::studio_submit_review()` + `_route_reviewer()` (defaults to workspace owner); sets `review_state=PENDING` and notifies approvers.
- **Approve action** — `apps/approvals/services.py::approve_post()`: transitions PlatformPosts `pending_review → approved`, records an `ApprovalAction`, notifies the author. Does **not** publish.
- **Publish path** — `apps/composer/views.py::publish_post()` sets `scheduled_at=now()` and moves PlatformPosts to `scheduled`; `apps/publisher/engine.py::poll_and_publish()` (Celery, ~15s) publishes them; the gate chokepoint `_dispatch_to_provider()` blocks anything whose `gate_id`/`content_hash` don't verify (human-authored `gate_bypassed` posts skip the AI gate, as today).
- **Email** — `apps/notifications/engine.py::notify()` / `_dispatch_email()` via the configured backend (SMTP in prod, console in dev), template `notifications/email/notification.{html,txt}`.

## What's new (the entire scope of this feature)

1. A compound view `send_for_publish(post_id)` in `apps/approvals` that orchestrates the three existing capabilities in order.
2. A post-copy email template `notifications/email/post_copy.{html,txt}`.
3. A config setting `REVIEW_COPY_EMAIL` (default `martin.maina@africacen.org`), editable in `apps/settings_manager` so it is not hard-coded.
4. A **Send** button on the reviewer's review screen.

## Behaviour

### The Send action (`apps/approvals/send_for_publish`)
Called by the assigned reviewer (POST, CSRF). In order:

1. **Approve** — call `approve_post(post, request.user, workspace)`. Sets `review_state=APPROVED` and records the `ApprovalAction` (audit trail preserved). Idempotent if already approved.
2. **Email a copy** — render `post_copy.{html,txt}` and send to `REVIEW_COPY_EMAIL` via the existing email backend. Sent immediately (does not wait for publish). One email per Send.
3. **Schedule publish** — reuse the approved-post publish path (`scheduled_at=now()`, PlatformPosts → `scheduled`). The poll loop publishes within ~15s. The gate at `_dispatch_to_provider()` still decides go/no-go.

**Gate is unchanged.** If the gate blocks a PlatformPost, the existing `_block` + notification path reports it; Send does not bypass the gate. The approval in step 1 satisfies the `review_state==APPROVED` precondition that `publish_post()` already enforces.

**Failure handling.**
- Email send failure must **not** silently swallow — log it and surface a non-fatal warning to the reviewer; publish still proceeds (the copy email is a notification, not a gate).
- If approve fails (e.g., post not in a sendable state), abort before emailing/publishing and show the reason.

### The email
- **Recipient:** `REVIEW_COPY_EMAIL` (single fixed address; default = Martin's, editable in settings_manager).
- **Contents:** caption, first comment, target platform(s), media, author name, reviewer (sender) name, and the post's review state.
- **Timing:** sent at Send time, so it will not contain the live published URL. The **live link arrives via the existing publish-success author notification** once the poll confirms publish. (If we later want a single email that waits for the live link, that's the explicitly-rejected Approach C.)

### UI
- A single **Send** button on the reviewer's review card (the approvals / Content Studio review surface).
- Visible only to the assigned `review_assignee` or a user with `approve_posts` permission.
- On success shows a confirm state, e.g. *"Sent — publishing to LinkedIn + emailed a copy."*
- Replaces the need to click Approve then Publish separately (the separate actions remain available; Send is the one-click path).

## Out of scope (YAGNI)
- No new approval workflow modes.
- No per-recipient / per-pillar email routing — one fixed address.
- No second "it's now live" email beyond the publish-success notification that already exists.
- No change to the gate, the publish engine, or the poll cadence.

## Testing
- Send on an assigned post: asserts `review_state==APPROVED` + one `ApprovalAction` recorded, exactly one copy email sent to `REVIEW_COPY_EMAIL`, and PlatformPosts moved to `scheduled`.
- Gate still authoritative: a post that fails the gate does **not** publish after Send (PlatformPost ends blocked, not published).
- Permissions: a non-assignee without `approve_posts` cannot Send (403); the assignee can.
- Email failure is non-fatal: simulated email error still approves + schedules publish, and logs/warns.
- `REVIEW_COPY_EMAIL` default + settings_manager override both respected.

## Files touched (anticipated)
- `apps/approvals/views.py` (+ `urls.py`) — new `send_for_publish` view.
- `apps/approvals/services.py` — thin orchestration helper if needed (keep the view slim).
- `templates/notifications/email/post_copy.{html,txt}` — new.
- `apps/settings_manager/defaults.py` (+ helpers/views/template) — `REVIEW_COPY_EMAIL`.
- The reviewer review template — add the **Send** button.
- `apps/approvals/tests/` — new tests above.
