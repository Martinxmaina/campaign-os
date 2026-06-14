# LinkedIn App — Access Request (permanent connection + follower analytics)

**Goal:** stop the "log in to LinkedIn every time" problem (make connections permanent / auto-refresh)
**and** pull follower/organization analytics. Both are unlocked by **one** LinkedIn product:
**Community Management API**.

You are the sole admin of the LinkedIn Developer app + the AfCEN Company Page, so you can complete
every step yourself.

---

## Why it happens today

Our app is running in **OIDC mode** — it only has "Sign In with LinkedIn using OpenID Connect" + "Share
on LinkedIn". Those scopes (`openid`, `profile`, `email`, `w_member_social`):

- issue **short-lived access tokens with NO refresh token** → LinkedIn forces a manual re-login, and
- have **no organization-read scope** → follower/company stats can't be fetched.

No amount of our code changes this — it's the LinkedIn app's product/scope grant. The fix is to add the
**Community Management API** product, which (a) issues **refresh tokens** (60-day access token that
auto-refreshes for ~1 year → effectively permanent) and (b) grants the org-read scopes that power
follower analytics.

---

## What to request in the LinkedIn Developer Portal

Add these **Products** to the app (https://www.linkedin.com/developers/apps → your app → **Products**):

1. **Sign In with LinkedIn using OpenID Connect** — keep (identity).
2. **Share on LinkedIn** — keep (`w_member_social`, member posting).
3. **Community Management API** — **ADD this** (the one that fixes both problems).
   - (Optional, later) *Marketing Developer Platform* — only if you want ads/deeper analytics.

Scopes these grant (no need to type them — they come with the products): `openid profile email`,
`w_member_social`, `r_organization_social`, `rw_organization_admin`, `r_organization_admin`,
`r_member_social`, `r_basicprofile`.

---

## Step-by-step (this is what unblocks "Community Management is blocked")

The usual reason CM API is blocked is the **Company Page verification** step — do it first:

1. **Settings tab** → make sure the app is **associated with the AfCEN LinkedIn Company Page**.
   - If not linked: set the Page under the app's "Company".
2. Still on **Settings** → click **Verify** next to the Page → LinkedIn generates a verification URL →
   open it while signed in as a **Page admin** (you) → approve. The app is now Page-verified.
3. **Products tab** → **Community Management API** → **Request access** → fill the short form
   (use-case text below). Once the Page is verified this is often granted immediately or within a few days.
4. **Products tab** → confirm **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**
   are also added.
5. **Auth tab** → leave the existing **Authorized redirect URLs** in place (don't remove them). They are
   the Campaign OS callback URLs, of the form
   `https://web-production-2f84d.up.railway.app/social-accounts/callback/<slug>/`.

### Use-case text to paste into the access form
> Campaign OS is AfCEN's internal content-operations tool. We publish our own approved posts to our
> LinkedIn Company Page and member profile, manage first comments on our posts, and read our own
> organization's follower statistics and post analytics for internal reporting. Single organization,
> internal staff only; no third-party data collection or resale.

---

## After LinkedIn grants it — the one-time change on our side (I do this)

Set these **Railway env vars** on the dispatch `web` **and** `worker` services, then I redeploy:

```
PLATFORM_LINKEDIN_COMPANY_CLIENT_ID     = <app client id>
PLATFORM_LINKEDIN_COMPANY_CLIENT_SECRET = <app client secret>
```

- Do **NOT** set `PLATFORM_LINKEDIN_PERSONAL_CLIENT_ID` — setting it forces the short-lived OIDC mode.
- With the company client id/secret set (and no personal one), the app runs in **`community_management`
  mode**: `/v2/me` profile, **refresh tokens**, and org scopes.

Then each LinkedIn account **reconnects once** (to mint a refresh-token-bearing token). After that:
- the access token **auto-refreshes** via our health-check + 401-retry → **no more manual re-login**
  (a silent refresh ~once a year), and
- **company follower analytics** start populating on the next hourly sync (the code is already shipped,
  it just needs the org-read scope this grant provides).

---

## Honest expectations

- **Permanence:** 60-day access token + ~365-day refresh token, refreshed automatically — effectively
  permanent for an internal tool (no human re-login in normal use).
- **Follower analytics:** works for the **Company Page** only. LinkedIn does **not** expose
  *personal-profile* follower counts via API — that's a platform limit, not ours.
- **Timeline:** the Page-verification (step 2) is the real gate; CM API access is usually quick once the
  Page is verified.
