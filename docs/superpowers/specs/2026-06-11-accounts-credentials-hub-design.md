# Design: Accounts & Credentials Hub

**Date:** 2026-06-11
**Status:** Approved — ready for implementation plan

## Problem

Managing what the org has connected is split across two pages: app keys live at
`/credentials/` (org-scoped, one per platform) and connected accounts live under
`/social-accounts/<workspace_id>/` (workspace-scoped). The user wants one place — "go
under credentials and delete each account" — and to manage **multiple accounts per
platform** (2 LinkedIn, 2 Instagram, …), all persistent.

Capabilities that **already exist** (no rebuild): multiple accounts per platform
(`SocialAccount` unique on `(workspace, platform, account_platform_id)`), per-account
delete (`social_accounts:disconnect`), encrypted persistence for both
`PlatformCredential` (app keys) and `SocialAccount` (OAuth tokens). They are just not
surfaced in one hub.

## Decisions (locked)

1. **Unified hub at `/credentials/`** — one card per platform.
2. **Each card shows app key + all connected accounts** for that platform.
3. **Accounts shown across all houses**, each labelled with its house; "Connect another"
   asks which house and routes to the existing connect flow.
4. Reuse existing connect/disconnect/credential-delete — no new account logic, no model
   change.

## Architecture

### Component 1 — `account_hub.py` (gathering helper)

`apps/credentials/account_hub.py`:

```python
def accounts_by_platform(org) -> dict[str, list[dict]]:
    """Return {platform: [{account, house}]} for every SocialAccount in the org,
    across all its workspaces. Keeps the view thin and is unit-testable."""
    from apps.social_accounts.models import SocialAccount
    rows = (
        SocialAccount.objects
        .filter(workspace__organization=org)
        .select_related("workspace")
        .order_by("platform", "workspace__name", "account_name")
    )
    out: dict[str, list[dict]] = {}
    for acc in rows:
        out.setdefault(acc.platform, []).append({
            "account": acc,
            "house": acc.workspace.name,
            "workspace_id": acc.workspace_id,
        })
    return out
```

### Component 2 — extend `credentials_list`

Add to the context: `accounts = accounts_by_platform(org)` and the org's workspaces
(`org.workspaces.filter(is_archived=False)`) for the "Connect another" house picker. Each
platform card already iterates `PLATFORM_FIELDS`; pass `accounts.get(platform, [])` per card.

### Component 3 — hub template (`templates/credentials/list.html`)

Each platform card gains a **Connected accounts** section under the app-key form:
- For each account: avatar (or initial), `account_name`, a **house badge**
  (`{{ house }}`), a status pill (`connection_status` / `needs_reconnect`), and actions:
  - **Reconnect** → `social_accounts:reconnect` (workspace_id, account.id)
  - **Delete** → `social_accounts:disconnect` (workspace_id, account.id), POST + confirm
- A **"+ Connect another"** control: a tiny `<select>` of houses → on submit, navigate to
  `social_accounts:connect` for the chosen `workspace_id` (the connect page lists platforms;
  the user picks this platform there). CSP-safe (Alpine `@change`, no inline handler).
- If a platform has no app key configured, show the existing "not configured" state and
  disable "Connect another" (can't OAuth without the app key).

### Component 4 — multi-account verification

No code change needed for multiple accounts. The plan includes a test proving the hub lists
two accounts of the same platform (different `account_platform_id`) under one card, each
deletable independently.

## Data model

No migration. Uses existing `PlatformCredential`, `SocialAccount`, `Workspace`,
`Organization`.

## Files

**New:**
- `apps/credentials/account_hub.py`
- `apps/credentials/tests/test_account_hub.py`

**Modified:**
- `apps/credentials/views.py` — `credentials_list` gathers accounts + houses
- `templates/credentials/list.html` — connected-accounts section + connect-another picker

## Testing

- `accounts_by_platform`: groups by platform across two workspaces; includes house name;
  empty platform → absent/empty list.
- `credentials_list` context: includes `accounts` keyed by platform and the houses list.
- Hub template: renders two same-platform accounts (e.g. two `linkedin_personal`) under one
  card with distinct house badges; each has a delete form pointing at the correct
  `disconnect` URL (workspace_id + account_id).
- "Connect another" select lists the org's houses and targets `social_accounts:connect`.
- App-key save/remove still works (existing tests stay green).
- Non-admin sees read-only (no delete/connect controls).

## Out of scope

WAIIS/"os" workspace dedupe, analytics, approvals, Resend. No changes to the OAuth connect
or disconnect logic — the hub only links to them.
