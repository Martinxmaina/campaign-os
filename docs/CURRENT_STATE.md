# Campaign OS — Current State

_Last updated: 2026-06-11_

## What Campaign OS is

Campaign OS is AfCEN's internal content-operations platform. It takes a content idea
from the team's planning sheet all the way to a published social post, with an AI
drafting agent and an editorial gate in between.

It runs as **two connected services on Railway**:

| Service | URL | Role |
|---|---|---|
| **Campaign OS** (Django) | `https://web-production-2f84d.up.railway.app` | The app you log into — intake board, composer, approvals, calendar, publishing |
| **agent-service** (FastAPI + DeepSeek) | `https://web-production-e7cf9.up.railway.app` | The "brain" — HERALD drafting, the content gate, news, deliberation |

The Django app calls the agent-service over signed HTTP. The agent-service runs
**DeepSeek-V4 via Azure AI Foundry** — every AI draft, gate check, and news digest
is generated there.

---

## What works today

| Capability | Status | Notes |
|---|---|---|
| **Google Sheets sync** | ✅ Live | Reads the team's intake sheet every 15 min. Auto-detects the tab name. 17 items synced. |
| **Intake board** | ✅ Live | `/console/intake/` — shows synced ideas with sensitivity, pillar, owner, links. |
| **HERALD drafting (DeepSeek)** | ✅ Live | Generates post drafts grounded in the real idea + AfCEN's knowledge. Verified producing real copy. |
| **Compose → publish (LinkedIn personal)** | ✅ Live | A real post went out to Martin Maina's LinkedIn (`urn:li:share:7470540320519233536`). |
| **Credentials in the UI** | ✅ Live | `/credentials/` — add platform OAuth keys in-app (encrypted), no redeploy. |
| **Publish gate** | ✅ Live | AI/HERALD content must pass the content gate; human-composed posts bypass it. |
| **Login** | ✅ Email/password | Google sign-in configured (pending web-client verification). |
| **Sensitivity controls** | ✅ Live | `private_hold` / `confidential` items are blocked from publishing. |

## What is not yet live

| Capability | Status | Blocker |
|---|---|---|
| **AfCEN company-page posting** | ⛔ Blocked | LinkedIn's **Community Management API** access is **not approved** (see below). |
| **AI drafts in the Approvals queue** | 🔧 Pending | HERALD drafts aren't yet tagged into the AI Approvals list — small wiring gap. |
| **Calendar integration on the board** | 🔧 Planned | "Add to calendar" from the intake board — designed, not built. |
| **X / Facebook / Instagram posting** | 🔧 Pending creds | Connectors built; need each platform's developer-app credentials. |

---

## Posting media to the AfCEN **company** page — how it works and where it stands

### How it is meant to work
Publishing to a LinkedIn **company page** uses LinkedIn's organization-posting API.
The flow is:

1. Add the LinkedIn **company** app credentials at `/credentials/` (LinkedIn Company card).
2. Connect the AfCEN company page via OAuth — this needs the scope
   **`w_organization_social`** (post on behalf of an organization) plus
   `r_organization_social` (read post status).
3. Compose or approve a post, attach media, and publish — Campaign OS calls the
   organization-posting endpoint with the AfCEN page URN as the author.

### Current status: **not yet possible**
LinkedIn refused the connection with:

> `OAuth error: Scope "w_organization_social" is not authorized for your application`

That scope is only granted once a LinkedIn app is **approved for the Community
Management API**. AfCEN's application for that product was **blocked / not approved**
by LinkedIn. This is a **LinkedIn policy gate, not a Campaign OS limitation** — no
third-party tool can post to a company page without that approval.

**What this means in practice:**
- **Personal-profile posting works now** (proven live). The campaign can run through
  team members' personal LinkedIn profiles immediately.
- **Company-page posting will light up automatically** — with no code change — the
  moment LinkedIn approves the Community Management API for the AfCEN app. The
  credentials slot and the connector are already built and waiting.

### Options to unblock company posting
1. **Re-apply / appeal** the Community Management API request (Products tab on the
   LinkedIn app), with a clear "managing our own organization's page" use case.
2. **Post via a personal profile** in the meantime (works today).
3. **Use LinkedIn's native scheduler / manual posting** for the company page until the
   API is approved, while Campaign OS handles drafting + the rest of the pipeline.

---

## The end-to-end loop (target)

```
Google Sheet → Intake board → HERALD drafts (DeepSeek) → editorial review/approval
   → publish to LinkedIn (personal ✅ / company ⛔ pending LinkedIn approval)
```

Everything left of "publish" works today. Publishing works for personal LinkedIn now;
company-page publishing is built and waiting on LinkedIn's API approval.
