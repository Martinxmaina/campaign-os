# IA Redesign — Option 01 "Group & Home"

**Date:** 2026-06-27
**Status:** Design — awaiting user review
**Decision:** User reviewed three IA options (artifact `e4bfe6e6`) and chose **Option 01 — Group & Home** (lightest touch), with scope = **navigation + page density**, audience = **role-based homes**.

---

## 1. Goal

The app exposes ~30 sidebar links across 9 groups to every user regardless of role, with 4+ ways to start content, 3 overlapping "approval" screens, and no front door. New users are overwhelmed.

Option 01 fixes the **ordering** problem with the lightest possible touch:

1. Collapse the ~30 links into a **short, stable spine** (Home, Create, Calendar, Review, Inbox, Analytics, More).
2. Add a **role-aware Home** as the new landing page — the missing front door.
3. **Filter the menu by role** — a user only sees the groups their role uses.
4. **Merge the duplicate "start content" front doors** into one.
5. Apply a **page-density rule** to the busiest screens, starting with Compose.

## 2. Non-goals (explicitly out of scope for Option 01)

These belong to Options 02/03 and are **not** done here:

- We do **not** merge the *logic* of the three approval screens into one queue (that's Option 02's "Review inbox").
- We do **not** move or rename existing URLs/route names. Existing pages keep their routes; we only change how they're *reached* from the menu.
- We do **not** rebuild the app shell into "spaces" (Option 03).
- We do **not** rebuild the scattered settings pages — we only group their *links* under one menu.

This keeps risk low: almost everything is template/nav work plus one new Home view.

## 3. The new navigation

### 3.1 Primary spine (every role sees these)

| Item | Routes to | Replaces today's |
|------|-----------|------------------|
| **Home** | new `home` view (§4) | *(nothing — new default landing)* |
| **Create** | `composer:compose`, with a dropdown for the other create modes (§5) | "+ New" dropdown · "Create Idea" nav (`composer:create_landing`) |
| **Calendar** | `calendar:calendar` | "Publish" |
| **Review** | role-aware (§3.3) | "AI Approvals", "Drafts" console links |
| **Inbox** | `inbox:feed` | "Social Inbox" |
| **Analytics** | `analytics:index` | "Analytics" (unchanged, now part of the spine) |
| **More ▾** | drawer (§3.2) | the Intelligence-console group |

Notifications moves to a **bell icon in the top bar** (it already has the unread badge) rather than a nav line.

### 3.2 "More ▾" drawer (collapsed by default; operator/occasional tools)

Brain (`/console/brain`), Content pipeline (`/console/pipeline`), Agents (`/console/agents`), Breakers (`/console/breakers`), Healing (`/console/healing`), Learning (`/console/learning`), Diffs (`/console/diffs`), News (`/console/news`), Intake (`/console/intake`), Intelligence playground, Media Library, Connect channels.

Items in More are still filtered by permission (e.g. agent-control surfaces only show for admins).

### 3.3 Role groups (shown only when the user has the permission)

Rendered as **collapsible groups below the spine**, each behind its existing permission gate:

- **Joseph ▸** (`can_access_joseph`): Today, Pipeline, Knowledge, My content, Voice, Decks.
- **Relationships ▸** (`can_manage_crm`): Organizations, Contacts, Deal pipeline, Import *(CRM)* + Mailboxes, Reply triage, Suppression *(Outreach)*.
- A content-team member with none of these permissions sees **only the spine + More** — no empty groups, no machinery they can't use.

"Review" target by role:
- Member (author only): `approvals:queue` (their personal queue).
- Approver / owner / `approve_posts`: `/console/approvals` (owner-routed AI Approvals).
- Each target keeps a visible link to the other approval views so nothing becomes unreachable — but only **one** "Review" item sits in the spine.

### 3.4 Settings (gear menu)

A single **gear menu** (top bar / footer) groups links to the existing settings pages — no page rebuilds:
Account settings, Workspace settings, Approvals rules, Content Intake (Sheet), Platform Credentials, Team, Notification preferences, API keys, Org settings, Workspace switcher.

## 4. Role-aware Home (new)

New route `home` (per workspace) becomes the **default post-login landing** (replaces the calendar default). One template with **role-conditional card sections**; each card reuses existing querysets — no new data models.

Cards by audience (a user sees the union of cards their role unlocks):

- **Everyone (content):**
  - *Needs your sign-off* — posts assigned to you for review (if `approve_posts` or assigned reviewer).
  - *Your drafts* — your draft posts, newest first.
  - *Going out soon* — posts scheduled in the next 7 days.
  - *Inbox* — count of unread inbox messages → link.
  - *Recent performance* — last-N published posts with headline metrics (if analytics enabled).
  - Primary CTA: **New post**.
- **Owner / admin (Martin):** + *Team approvals pending*, *Intake to triage*, *System health* (open breakers / healing incidents / agent fleet status).
- **Principal (`can_access_joseph`):** the Joseph "Today" essentials — briefs needing attention, approvals, pipeline movement (reuse `joseph:home` data; or a prominent "Open Joseph" card).
- **Campaign owner (`can_manage_crm`):** + *Deals needing action*, *Replies to triage*.

Empty states are invitations ("No drafts yet — start a post"), never dead ends.

## 5. Merging the "start content" front doors

- Retire `composer:create_landing` as a top-level destination → redirect it to the new **Create** flow (route kept as a 302 so old links/bookmarks survive).
- The **Create** spine item opens the compose page (write a post). A small attached dropdown offers the other modes without giving each its own top-level link:
  - **New post** → `composer:compose`
  - **Capture idea** → idea modal (`composer:idea_create`) / idea board
  - **Browse AI ideas** → `/console/ideas`
  - **From intake** → `/console/intake`
- Net: one obvious front door; the rare modes are one click deeper.

## 6. Page density (busy-screen rule)

Applied to the busiest pages, in priority order. Four principles:

1. **One primary action** — each page has a single obvious next step (e.g. Compose → "Schedule / Publish"), visually dominant.
2. **Progressive disclosure** — optional/rare fields fold into labelled collapsed sections, expanded on demand.
3. **Show, don't bury** — put the live preview beside the editor instead of below the fold.
4. **Consistent shell** — shared page header, spacing scale, and button language across pages.

**Priority pages:** (1) Compose — *worked example below*; (2) Calendar/Publish; (3) Content board / Studio; (4) Inbox detail. Density work ships page-by-page after the nav lands.

**Compose worked example.** Today the page stacks ~12 equal-weight fields (caption, platforms, media, campaign, track, pillar, tags, first comment, schedule, assign, approval state, preview). After: a two-pane top (write caption + media + channels | live preview), then three folded sections — *Campaign/track/pillar/tags*, *First comment & schedule*, *Send for review* — and one primary **Schedule / Publish** button.

## 7. Implementation surface

- `templates/base.html` — the sidebar nav (lines ~245–925): rebuild the link list into spine + More drawer + role groups + gear menu; move Notifications to a top-bar bell. This is the bulk of the work.
- **New Home:** `home` view + URL (workspace-scoped) + `templates/home/home.html` with role-conditional card partials. Update post-login redirect / workspace landing to point here.
- `composer:create_landing` → redirect to Create flow; add the Create dropdown to the spine item.
- `templates/composer/compose.html` — density refactor (two-pane + folded sections + single primary CTA).
- No migrations expected (Home reuses existing models).

## 8. Rollout / phasing

1. **Phase A — Nav + Home.** New spine, More drawer, role groups, gear menu, role-aware Home, idea-door merge. (The big perceived win.)
2. **Phase B — Compose density.** Refactor compose.html to the two-pane + folded layout.
3. **Phase C — Remaining density pages.** Calendar, content board, inbox detail — one at a time.

Each phase is independently shippable and reversible (nav is template-level).

## 9. Testing

- Nav renders correctly for each role: content member (spine + More only), campaign owner (+ Relationships), principal (+ Joseph), admin (full + System health card).
- Home renders the right card set per role with no crashes on empty data.
- `create_landing` 302s to the Create flow; old idea/post links still resolve.
- Compose still saves/schedules/publishes correctly after the density refactor (existing publish-gate tests must stay green).
- No existing route names removed (grep for reverse() usages before retiring any).

## 10. Risks

- **base.html is large and central** — a nav mistake affects every page. Mitigate: change the link structure only, keep existing CSS/shell, test per-role rendering.
- **Role detection for Home/Review** must match existing permission helpers (`can_access_joseph`, `can_manage_crm`, `approve_posts`) exactly — reuse them, don't reinvent.
- **Hiding items in "More"** must not hide something a given role needs daily — keep More for genuinely occasional/admin tools; validate the split with the user during review.
