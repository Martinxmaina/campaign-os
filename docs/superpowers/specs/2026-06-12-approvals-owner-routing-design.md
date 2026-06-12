# Design: Approvals + Owner Routing

**Date:** 2026-06-12
**Status:** Approved — ready for implementation plan

## Problem

HERALD-drafted intake items need to land in an **AI Approvals** queue **routed to the
responsible owner**, who approves them so they proceed to the gate → publish path. Today
the console's AI Approvals reads the agent-service (`/approvals?assignee=me`), which never
receives our drafts, so the queue is empty. The native Django approval flow
(`submit_for_review`) notifies *all* reviewers and has **no per-person assignee**, so it
can't route by owner.

## Decisions (locked)

1. **Django creates the approval** (no agent-service change).
2. **Route by owner**, pillar map: `energy→Dennis · agribusiness→Carren · ai→Joseph ·
   digital→Nduta · minerals→Dennis`.
3. **Fallback** to the **workspace owner/admin** when the owner is unmapped/unknown.

## Architecture

### Component 1 — Owner resolution (`apps/content_intake/owner_routing.py`)

```python
OWNER_BY_PILLAR = {
    "energy": "Dennis", "agribusiness": "Carren", "ai": "Joseph",
    "digital": "Nduta", "minerals": "Dennis",
}

def resolve_reviewer(intake):
    """Return the User who should review this intake item.
    1) a User matching intake.owner_raw (name/email, case-insensitive)
    2) else the pillar/sector → owner-name → User
    3) else the workspace owner/admin (OrgMembership/WorkspaceMembership owner/admin)
    Returns None only if the workspace has no owner/admin at all.
    """
```

- Owner-name → User: case-insensitive match on `User.name` (first token) or `email` local-part,
  scoped to users who are members of the intake's workspace.
- Pillar match: lowercase `intake.pillar_theme`/sector against `OWNER_BY_PILLAR` keys
  (reuse `sector_map.map_pillar_to_sector` for normalization).

### Component 2 — `Post.review_assignee` + `Post.review_state` + assign on draft

Two new fields on `Post` (one migration), used as the **authoritative AI-approval state**
independent of PlatformPost transitions (so channel-less HERALD drafts still appear in the
queue — `submit_for_review` only moves PlatformPosts and would no-op for a Post with none):

- `review_assignee` → nullable FK to `settings.AUTH_USER_MODEL` (`related_name="review_queue"`).
- `review_state` → CharField choices `none | pending | approved | changes_requested | rejected`,
  default `none`.

In `apps/content_intake/draft_post.ensure_draft_post`, after the Post is created/linked:
- set `post.review_assignee = resolve_reviewer(intake)` if not already set,
- set `post.review_state = "pending"` (only if currently `none`/`changes_requested` — idempotent;
  never downgrade an already-approved post),
- if the Post has PlatformPosts, also call `submit_for_review(post, actor, workspace)` so the
  per-channel cards reflect pending_review (best-effort; ignored when channel-less).

### Component 3 — Django AI Approvals queue

Repurpose `apps/approvals/console_views.ai_approvals` to read **Django**:
- Query `Post` objects in the user's workspace(s) with `review_state == "pending"` and either
  `review_assignee == request.user` OR (the user is workspace owner/admin → show all pending).
- Render `templates/console/approvals.html` with each card: title, pillar/house, assignee,
  caption preview, **Approve / Request changes / Reject** buttons.
- Decisions (`approval_decide` operates on a Django `Post` id):
  - **Approve** → set `review_state="approved"`, record `ApprovalAction(action=APPROVED)`, and
    transition any PlatformPosts toward scheduled/publish via the existing gate path (gate_bypassed/
    gate handling already in place).
  - **Request changes** → `review_state="changes_requested"`, `ApprovalAction(CHANGES_REQUESTED)`.
  - **Reject** → `review_state="rejected"`, `ApprovalAction(REJECTED)`.

### Component 4 — wiring

- `config/console_urls.py`: keep `console:approvals` + `console:approval-decide` names; point
  `approval_decide` at the Django Post flow.
- The bulk "Draft selected" / manual draft already create the Post; assignment happens in
  `ensure_draft_post`, so every HERALD draft is auto-routed.

## Data model

- One migration: `Post.review_assignee` (nullable FK) + `Post.review_state` (CharField,
  default `none`). No other model changes.

## Files

**New:**
- `apps/content_intake/owner_routing.py`
- `apps/content_intake/tests/test_owner_routing.py`
- `apps/composer/migrations/00XX_post_review_assignee.py`

**Modified:**
- `apps/composer/models.py` — `review_assignee` field
- `apps/content_intake/draft_post.py` — assign + submit on draft
- `apps/approvals/console_views.py` — Django-backed `ai_approvals` + `approval_decide`
- `templates/console/approvals.html` — queue UI with approve/changes/reject
- `apps/approvals/tests/` — queue + decide tests

## Testing

- `resolve_reviewer`: owner_raw match → that user; pillar map (energy→Dennis user); fallback to
  workspace owner when unmapped; None when no owner exists.
- `ensure_draft_post`: sets `review_assignee` (from `resolve_reviewer`) + `review_state="pending"`;
  idempotent — re-draft never downgrades an already-`approved` post.
- AI Approvals view: assignee sees their `review_state="pending"` Posts; non-assignee member does
  not; owner/admin sees all pending; login required.
- `approval_decide`: approve → `review_state="approved"` + ApprovalAction + PlatformPost transition;
  request-changes → `changes_requested`; reject → `rejected`; cross-workspace isolation.

## Out of scope

agent-service changes; Joseph-personal-channel publish gate (already exists); Resend reminders
(#7); analytics (#6); pipeline (#9).
