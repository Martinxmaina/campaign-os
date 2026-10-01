# 05 — Accounts and Access Register

This register lists every account, system, repository, domain, environment, tool, dataset and third-party service that Campaign OS uses or depends on.

## How to read and complete it

- **"Evidence"** says where in the repository the dependency was found.
- **"Owner / login"** and **"Billing"** cannot be read from code. Where the repo gives no answer, the cell says **TO CONFIRM**. The outgoing owner must fill these in at the handover meeting.
- **"AfCEN-controlled?"** answers one question: does an AfCEN organisational account (not a person's private account) own this today?
  - **No** means it is known to sit in a personal account.
  - **TO CONFIRM** means the repo does not say.

The target end state for every row:
- owned by an AfCEN organisational login,
- at least two AfCEN staff as admins,
- the outgoing developer's access removed or reduced to what AfCEN chooses,
- billing on an AfCEN payment method.

No credentials appear in this document. See [06-credential-transfer.md](06-credential-transfer.md).

---

## 1. Source code repositories

| # | Item | Purpose | Owner / login | AfCEN-controlled? | Billing | Evidence |
|---|---|---|---|---|---|---|
| R1 | GitHub `Martinxmaina/campaign-os` | This repository: the Campaign OS Django app | Personal GitHub user **Martinxmaina**. All 81 commits are authored as `martinnjoroge077@gmail.com`. | **No** (personal account) | GitHub free/personal plan assumed; Actions minutes billed to that account. **TO CONFIRM.** | `git remote -v`, `git log` |
| R2 | GitHub `africacen/campaign-os` | Intended public AGPL source link | **TO CONFIRM** whether this org or repo exists | **TO CONFIRM** | — | `config/settings/base.py:17`, `templates/about.html:13` |
| R3 | agent-service repository | FastAPI intelligence plane: gate, HERALD, wiki, brain | **TO CONFIRM.** Only a laptop path `/Users/macbook/Downloads/WAIIS/agent-service` is recorded. | **TO CONFIRM** | — | `docs/superpowers/plans/2026-06-12-tb1-joseph-voice-profile.md:9-11` |
| R4 | `brightbeanxyz/brightbean-studio` | Upstream open-source project this was forked from (commit `3d56b44`) | Third party (BrightBean) | N/A: public upstream, no account needed | Free (AGPL-3.0) | `docs/ADR-002-upstream-pin.md` |

**Action for R1:** transfer the repository to an AfCEN GitHub organisation (GitHub → Settings → Transfer ownership). Redirects keep working. Then:
- update `README.md`, `NOTICE` and `SOURCE_REPO_URL`;
- replace `.github/CODEOWNERS` (currently `@JanSchm`, the upstream maintainer) with AfCEN maintainers;
- turn on branch protection for `main`.

---

## 2. Hosting and environments

| # | Item | Purpose | Owner / login | AfCEN-controlled? | Billing | Evidence |
|---|---|---|---|---|---|---|
| H1 | Railway project: Campaign OS (`waiis-dispatch-platform`) | Production. Services `web`, `worker`, Postgres, Redis. | **TO CONFIRM** (Railway account or team) | **TO CONFIRM** | Railway is paid, usage-based (plan + compute + database). Plan, payment method and monthly cost **TO CONFIRM**. | `railway.toml`, `README.md` "Deployment", `docs/platform-console-deploy.md` |
| H2 | Railway project: agent-service | Production intelligence plane: FastAPI web, its own Postgres, and any worker | **TO CONFIRM** | **TO CONFIRM** | As above. **TO CONFIRM.** | `docs/CURRENT_STATE.md`, `README.md` |
| H3 | Azure subscription | Azure AI Foundry deployment of DeepSeek-V4 used by agent-service; self-hosted Firecrawl on Azure Container Apps | **TO CONFIRM** | **TO CONFIRM** | Paid (per-token model usage + container hosting). **TO CONFIRM.** | `README.md` tech stack; `docs/phase2.md` §3.4; `config/settings/base.py:534-545` |
| H4 | Staging / test environment | — | **None exists in the repo.** Only production on Railway, plus local development. | — | — | `config/settings/` has development, production and test only |
| H5 | Local development | Developer laptops: Postgres + Redis + `uv` | Individual developers | N/A | — | `README.md`, `Makefile`, `docker-compose*.yml` |
| H6 | GitHub Actions CI | Lint, typecheck, tests, Docker build, gitleaks. **Does not deploy.** Needs no repository secrets. | Runs under R1 | Follows R1 | Included in GitHub plan | `.github/workflows/ci.yml` |

**Unused deployment files** (not live; inherited from BrightBean): `app.json` (Heroku), `render.yaml` (Render), `docker-compose.prod.yml` + `Caddyfile` (self-hosted). Nothing suggests any account exists on Heroku or Render for this project.

---

## 3. Domains and URLs

| # | Item | Purpose | Owner / login | AfCEN-controlled? | Billing | Evidence |
|---|---|---|---|---|---|---|
| D1 | `web-production-2f84d.up.railway.app` | Live Campaign OS URL; LinkedIn OAuth redirect URLs point here | Railway-generated subdomain. It belongs to whoever owns H1 and cannot be moved separately. | Follows H1 | Included in Railway | `docs/CURRENT_STATE.md`, `docs/api/*.md`, `docs/operations/linkedin-app-access-request.md` |
| D2 | `web-production-e7cf9.up.railway.app` | Live agent-service URL | Follows H2 | Follows H2 | Included in Railway | `docs/CURRENT_STATE.md`, `docs/platform-console-deploy.md` |
| D3 | `the-nexus-brief.ghost.io` | The Nexus Brief newsletter and blog (Ghost) | Ghost(Pro) site owner **TO CONFIRM** | **TO CONFIRM** | Ghost(Pro) hosting is paid. **TO CONFIRM.** | `config/settings/base.py:492`, `.env.example` |
| D4 | `africacen.org` | AfCEN's main domain: terms and privacy pages linked from signup, `unsubscribe@africacen.org`, `support@africacen.org`, staff emails | AfCEN (assumed) | **TO CONFIRM** (registrar and DNS login) | Domain renewal **TO CONFIRM** | `templates/account/signup.html:119-121`, `apps/outreach/senders.py:103` |
| D5 | `app.waiis.org` | Set as the Django "Site" domain by a migration; used in some generated absolute links | **TO CONFIRM** whether registered and by whom | **TO CONFIRM** | **TO CONFIRM** | `apps/accounts/migrations/0005_set_site_campaign_os.py:8` |
| D6 | `api.africacen.org` | Mentioned as a possible future custom domain only | Not set up | — | — | `docs/api/platform-api.md:17` |
| D7 | Email sending domain for Resend / SMTP | The `DEFAULT_FROM_EMAIL` domain must be verified in Resend (SPF/DKIM DNS records) | **TO CONFIRM** which domain and who manages its DNS | **TO CONFIRM** | — | `config/settings/base.py:311-315` |

**Note on D1.** If the Railway project is ever recreated or moved, the URL changes. These must then be updated:
- every OAuth redirect URI registered with LinkedIn, Google, Meta and X;
- `APP_URL`;
- `STUDIO_BASE_URL`;
- any external consumers of the API.

Mapping a custom AfCEN domain (for example `campaign.africacen.org`) in Railway before handover removes this dependency.

---

## 4. Third-party services

| # | Service | Used for | Owner / login | AfCEN-controlled? | Billing | Evidence |
|---|---|---|---|---|---|---|
| S1 | **Blotato** (`my.blotato.com`, API `backend.blotato.com/v2`) | Main publishing route for Instagram, Facebook, Threads, Bluesky, LinkedIn (personal and page) and X. The social network logins are stored **inside Blotato**, not in Campaign OS. | **TO CONFIRM** | **TO CONFIRM** | Paid subscription. Plan and renewal date **TO CONFIRM**. If it lapses, these channels stop publishing. | `providers/blotato.py`, `docs/superpowers/specs/2026-06-23-blotato-integration-design.md` |
| S2 | **Ghost(Pro)** | Nexus Brief posts and newsletter sends; post metrics | **TO CONFIRM** (Ghost staff owner) | **TO CONFIRM** | Paid. **TO CONFIRM.** | `providers/ghost.py` |
| S3 | **DeepSeek** (`platform.deepseek.com`) or **Azure AI Foundry** | Direct AI generation in AI Studio and the campaign composer (`DEEPSEEK_*`). agent-service uses DeepSeek-V4 via Azure for HERALD and the gate. | **TO CONFIRM** which provider the Campaign OS `DEEPSEEK_API_KEY` belongs to | **TO CONFIRM** | Prepaid credits (DeepSeek) or Azure metered. **TO CONFIRM.** | `apps/common/deepseek_client.py` |
| S4 | **Resend** | Approval and Send emails (first-choice transport) | **TO CONFIRM** | **TO CONFIRM** | Free tier or paid. **TO CONFIRM.** | `apps/approvals/emailer.py` |
| S5 | **SMTP provider** | Invites, password reset, notification emails | **TO CONFIRM** (could be Google Workspace SMTP relay, Resend SMTP, etc.) | **TO CONFIRM** | **TO CONFIRM** | `EMAIL_*` settings |
| S6 | **Google Cloud project(s)** | OAuth clients for: (a) Sheets + Gmail + Calendar (`GOOGLE_SHEETS_CLIENT_ID`, a "Desktop app" client per `scripts/get_google_refresh_token.py`); (b) "Sign in with Google" (`GOOGLE_AUTH_CLIENT_ID`); (c) YouTube (`PLATFORM_GOOGLE_CLIENT_ID`), if used. Also the OAuth consent screen and API enablement. | **TO CONFIRM.** Should sit in AfCEN's Google Workspace organisation. | **TO CONFIRM** | Google APIs used here are free within quota | `config/settings/base.py:258-269`, `integrations/*.py` |
| S7 | **Google Workspace user accounts** | (a) The Google account that authorised `GOOGLE_SHEETS_REFRESH_TOKEN`; Sheets access runs as this person. (b) Joseph's and other owners' Gmail and Calendar, linked through `joseph.GoogleIntegration` rows. | **TO CONFIRM** which account minted the shared refresh token | Accounts at `@africacen.org` are AfCEN-controlled; a personal Gmail would not be | Workspace licences (AfCEN) | `apps/content_intake/sheets_sync.py`, `apps/joseph/models.py` |
| S8 | **LinkedIn Developer app** | Direct LinkedIn OAuth (personal posting; company page once approved) | `docs/operations/linkedin-app-access-request.md` says the reader (the outgoing developer) is "the sole admin of the LinkedIn Developer app + the AfCEN Company Page" | **No.** Single personal admin. Add AfCEN admins. | Free | `providers/linkedin*.py` |
| S9 | **LinkedIn AfCEN Company Page** | Target for company posts; the developer app must be verified against it | Page admins **TO CONFIRM** (see S8) | **TO CONFIRM** | Free | same |
| S10 | **X developer app** (`PLATFORM_TWITTER_*`) | Direct X provider (text only). In practice X publishes through Blotato. | **TO CONFIRM** whether an app exists | **TO CONFIRM** | X API tiers are paid above the free tier. **TO CONFIRM.** | `providers/twitter.py` |
| S11 | **X Premium** on the posting account | 25,000-character posts (`e5f43f9`) | Holder of the X account | **TO CONFIRM** | Paid monthly subscription on that X account | `providers/blotato.py` caption limit |
| S12 | **Meta developer app** (`PLATFORM_FACEBOOK_*`, `PLATFORM_INSTAGRAM_*`) | Direct Facebook, Instagram and Threads providers; a Meta App Review helper command exists | **TO CONFIRM** whether created and who is admin | **TO CONFIRM** | Free | `providers/facebook.py`, `apps/social_accounts/management/commands/instagram_review_test_calls.py` |
| S13 | **Sentry** | Error tracking, if `SENTRY_DSN` is set | **TO CONFIRM** whether used | **TO CONFIRM** | Free or paid tier. **TO CONFIRM.** | `config/settings/base.py:396-405` |
| S14 | **S3-compatible bucket** (the design spec names Cloudflare R2) | Media library files, if `STORAGE_BACKEND=s3`. Otherwise files are on the container or a Railway volume. | **TO CONFIRM** whether used | **TO CONFIRM** | Storage + egress. **TO CONFIRM.** | `config/settings/base.py:211-236`, `docs/phase2.md` §3.4 |
| S15 | **Firecrawl** (self-hosted, used by agent-service) | Web research for the wiki | See H3 | **TO CONFIRM** | See H3 | `docs/phase2.md` §3.4 |
| S16 | **jsdelivr CDN** | Front-end libraries loaded in the browser | Public CDN | N/A | Free | `templates/base.html` |
| S17 | BrightBean "Intelligence" SaaS | Inherited paid add-on. **Not used**; switched off because its env vars are unset. | — | — | None | `config/settings/base.py:507-517` |
| S18 | Claude Code (Anthropic) | AI coding assistant used during development (`.claude/` folder, `CLAUDE.md`) | Developer's own subscription | **TO CONFIRM** | Paid per seat. Not needed to run the system. | `.claude/`, `CLAUDE.md` |

### 4.1 The social media accounts themselves

Campaign OS publishes to accounts it does not own. Each must have AfCEN admins, independent of any one person.

| Account | Connected via | Owner / admins | AfCEN-controlled? |
|---|---|---|---|
| AfCEN LinkedIn Company Page | Blotato (page target) / direct (blocked) | **TO CONFIRM** | **TO CONFIRM** |
| WAIIS LinkedIn page (channel token `linkedin-waiis-page` appears in intake parsing) | Blotato / direct | **TO CONFIRM** | **TO CONFIRM** |
| Joseph's personal LinkedIn | Blotato or direct | Joseph | Personal, by nature |
| Martin Maina's personal LinkedIn (first live test post 2026-06-11) | direct | Martin | Personal. **Disconnect at handover** unless AfCEN wants it kept. |
| AfCEN / WAIIS X account(s) | Blotato | **TO CONFIRM** | **TO CONFIRM** |
| AfCEN / WAIIS Instagram, Facebook Page, Threads, Bluesky | Blotato | **TO CONFIRM** | **TO CONFIRM** |
| YouTube channel (if any) | direct | **TO CONFIRM** | **TO CONFIRM** |
| The Nexus Brief (Ghost) | direct API key | see S2 | **TO CONFIRM** |

The live list is in Campaign OS at `/credentials/` and in Django admin → Social accounts. Export it at handover and attach it to this register.

---

## 5. Datasets

| # | Dataset | Where it lives | Contains | Owner | AfCEN-controlled? | Notes |
|---|---|---|---|---|---|---|
| DS1 | Campaign OS production database | Railway Postgres (H1) | Users, posts, approvals, intake items, analytics, **CRM organisations and contacts (personal data)**, outreach send log, suppression list, encrypted OAuth tokens and platform credentials, API key hashes | Follows H1 | Follows H1 | Unreadable encrypted fields without `SECRET_KEY` + `ENCRYPTION_KEY_SALT`. Backups **TO CONFIRM** (runbook §3.5). |
| DS2 | agent-service database | Railway Postgres (H2) | Knowledge wiki and revisions, dossiers, gate run records (the compliance audit trail), agent episodes and playbooks, Joseph voice profile, notifications | Follows H2 | Follows H2 | Not documented in this repo |
| DS3 | Content-planning Google Sheet | Google Drive, sheet ID `1cHFwSI-W2B_sXMewVVUhPQJ16ZtFONGJl2OQux7UqJE` | The team's content register (source of the Content board) | **TO CONFIRM** (Drive owner) | **TO CONFIRM** | Read every 15 minutes. If moved to a different owner, re-share it with the account in S7(a). |
| DS4 | CRM tracker Google Sheet | Google Drive, ID in `CRM_TRACKER_SHEET_ID`, tab "Campaign OS — Pipeline" | Daily copy of the CRM pipeline | **TO CONFIRM** | **TO CONFIRM** | Off if the env var is unset |
| DS5 | Media files | Railway volume / container disk, or S3 bucket (S14) | Uploaded images, video, logos, voice notes | Follows storage choice | **TO CONFIRM** | **If local disk without a Railway volume, uploads are lost on every redeploy.** Check which applies. |
| DS6 | Ghost members / subscribers | Ghost(Pro) (S2) | Newsletter subscriber list (personal data) | Follows S2 | **TO CONFIRM** | |
| DS7 | Media and post history held by Blotato | Blotato (S1) | Copies of published posts and uploaded media | Follows S1 | **TO CONFIRM** | |
| DS8 | Railway logs | Railway | Application logs (may include email addresses and post text) | Follows H1/H2 | Follows H1/H2 | Retention per Railway plan |

**Personal data.** DS1, DS2 and DS6 hold personal data about funders, contacts and subscribers. AfCEN should record them in its data-protection register (Kenya Data Protection Act 2019, and GDPR for EU contacts) and decide on retention.

---

## 6. People with access today (as far as the repo shows)

| Person | Access evidenced in repo | Action at handover |
|---|---|---|
| Martin Maina (`martin.maina@africacen.org`; GitHub `Martinxmaina`, `martinnjoroge077@gmail.com`) | Sole committer; owner of R1; sole admin of S8 per ops doc; default recipient of Send copies; personal LinkedIn connected for testing | Transfer R1, add AfCEN admins on every row above, change `review.copy_email`, then reduce access as AfCEN decides |
| Joseph Nganga (principal) | Joseph approval gate (`JOSEPH_APPROVER_EMAIL`); Google Calendar/Gmail integration | Confirm his app role and Google integration |
| Nduta Njenga (campaign owner), Dennis, Carren, Roberto | Named content team; pillar routing | Confirm app accounts and roles in Members |
| Lazarus Magwaro (named "tech lead" in `docs/phase2.md:4`) | No commits in this repo | Confirm whether he should become the technical owner |
| `@JanSchm` (upstream BrightBean maintainer) | Listed in `.github/CODEOWNERS` only; has no access | Remove from CODEOWNERS |
| Anyone who self-registered | Owner role (bug G2) | Audit Members and `/admin/` user list |

The full list of application users is in Django admin → Users, and Organisation → Members. Export it at handover.

---

## 7. Handover confirmation checklist

To be completed together by the outgoing owner and AfCEN. Each line closes a **TO CONFIRM** above.

- [ ] R1: GitHub repo transferred to AfCEN organisation; CODEOWNERS and branch protection set
- [ ] R2: AGPL source link (`SOURCE_REPO_URL`, `/about/`, `NOTICE`) points to a real public repo
- [ ] R3: agent-service repository located and transferred
- [ ] H1/H2: Railway project owner, team members, plan, payment method, monthly cost recorded; AfCEN added as owner
- [ ] H1: Railway Postgres backups enabled and a restore tested
- [ ] H3: Azure subscription owner, billing, resources (AI Foundry deployment, Firecrawl) recorded
- [ ] D3/D4/D5/D7: registrar and DNS logins for `africacen.org`, `waiis.org` (if owned), email sending domain
- [ ] S1: Blotato account owner, plan, renewal; AfCEN admin added
- [ ] S2: Ghost(Pro) owner and plan; AfCEN owner added
- [ ] S3: DeepSeek / Azure key owner and billing
- [ ] S4/S5: Resend and SMTP account owners
- [ ] S6/S7: Google Cloud project owner; which Google account minted the shared refresh token; consent screen publishing status (Testing or In production)
- [ ] S8/S9: LinkedIn developer app and Company Page admins (at least two AfCEN staff)
- [ ] S10/S11/S12: X and Meta developer apps and X Premium: exist? owner? billing?
- [ ] S13/S14: Sentry and object storage: used? owner?
- [ ] §4.1: every connected social account listed with its AfCEN admins
- [ ] DS3/DS4: Google Sheets owned by an AfCEN Drive / shared drive
- [ ] DS5: storage confirmed persistent
- [ ] §6: user list exported and reviewed; unknown accounts removed
- [ ] All secrets in [06-credential-transfer.md](06-credential-transfer.md) received through the secure route and rotated where marked
