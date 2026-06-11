# Accounts & Credentials Hub — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/credentials/` a single hub: per platform, show the app key (save/remove) AND every connected account across all houses, with connect-another and delete-each.

**Architecture:** A thin `account_hub.accounts_by_platform(org)` helper gathers `SocialAccount`s org-wide grouped by platform; `credentials_list` attaches them to each platform card; the template adds a connected-accounts section that reuses the existing `social_accounts:connect`/`disconnect`/`reconnect` routes. No model change, no new account logic.

**Tech Stack:** Django 5.1, HTMX + Alpine (CSP-safe — no inline handlers). uv at `/Users/macbook/.local/bin/uv`.

**Spec:** `docs/superpowers/specs/2026-06-11-accounts-credentials-hub-design.md`

**Test command:** `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <path> -p no:warnings -q`

---

## File Map

**New:**
- `apps/credentials/account_hub.py` — `accounts_by_platform(org)`
- `apps/credentials/tests/test_account_hub.py`

**Modified:**
- `apps/credentials/views.py` — `credentials_list` attaches accounts + houses
- `templates/credentials/list.html` — connected-accounts section + connect-another picker + CSP-safe confirm

---

## Task 1: `accounts_by_platform` helper

**Files:**
- Create: `apps/credentials/account_hub.py`
- Test: `apps/credentials/tests/test_account_hub.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/credentials/tests/test_account_hub.py
import pytest
from apps.credentials.account_hub import accounts_by_platform


@pytest.mark.django_db
def test_groups_accounts_by_platform_across_houses(organization):
    from apps.workspaces.models import Workspace
    from apps.social_accounts.models import SocialAccount
    ws1 = Workspace.objects.create(organization=organization, name="WAIIS")
    ws2 = Workspace.objects.create(organization=organization, name="AfCEN")
    SocialAccount.objects.create(workspace=ws1, platform="linkedin_personal",
        account_platform_id="li-1", account_name="Martin")
    SocialAccount.objects.create(workspace=ws2, platform="linkedin_personal",
        account_platform_id="li-2", account_name="Joseph")
    SocialAccount.objects.create(workspace=ws1, platform="twitter",
        account_platform_id="tw-1", account_name="WAIIS X")

    out = accounts_by_platform(organization)
    assert set(out.keys()) == {"linkedin_personal", "twitter"}
    li = out["linkedin_personal"]
    assert len(li) == 2                                  # two LinkedIn accounts
    houses = {row["house"] for row in li}
    assert houses == {"WAIIS", "AfCEN"}                  # labelled by house
    assert all("workspace_id" in row and "account" in row for row in li)


@pytest.mark.django_db
def test_empty_org_returns_empty(organization):
    assert accounts_by_platform(organization) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/credentials/tests/test_account_hub.py -p no:warnings -q`
Expected: FAIL — `ModuleNotFoundError: apps.credentials.account_hub`

- [ ] **Step 3: Implement the helper**

```python
# apps/credentials/account_hub.py
"""Gather an org's connected social accounts grouped by platform, for the
unified Accounts & Credentials hub. Keeps the view thin + unit-testable."""
from __future__ import annotations


def accounts_by_platform(org) -> dict[str, list[dict]]:
    """Return {platform: [{account, house, workspace_id}]} for every SocialAccount
    in ``org`` across all its workspaces. Ordered platform → house → name."""
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

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/credentials/tests/test_account_hub.py -p no:warnings -q`
Expected: PASS (2 cases)

- [ ] **Step 5: Commit**

```bash
git add apps/credentials/account_hub.py apps/credentials/tests/test_account_hub.py
git commit -m "feat(credentials): accounts_by_platform helper — org-wide accounts grouped by platform"
```

---

## Task 2: Attach accounts + houses to the credentials view

**Files:**
- Modify: `apps/credentials/views.py`
- Test: `apps/credentials/tests/test_account_hub.py` (add a view test)

- [ ] **Step 1: Write the failing test**

Append to `apps/credentials/tests/test_account_hub.py`:

```python
@pytest.mark.django_db
def test_credentials_list_context_has_accounts_and_houses(client, org_owner, organization):
    from apps.workspaces.models import Workspace
    from apps.social_accounts.models import SocialAccount
    from django.urls import reverse
    ws = Workspace.objects.create(organization=organization, name="WAIIS")
    SocialAccount.objects.create(workspace=ws, platform="linkedin_personal",
        account_platform_id="li-9", account_name="Martin")
    client.force_login(org_owner)
    resp = client.get(reverse("credentials:list"))
    assert resp.status_code == 200
    # The page lists the connected account + its house.
    assert b"Martin" in resp.content
    assert b"WAIIS" in resp.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/credentials/tests/test_account_hub.py::test_credentials_list_context_has_accounts_and_houses -p no:warnings -q`
Expected: FAIL — account name not in the page (not yet rendered).

- [ ] **Step 3: Extend `credentials_list`**

In `apps/credentials/views.py`, add the import at the top with the others:

```python
from apps.credentials.account_hub import accounts_by_platform
```

In `credentials_list`, after `existing` is built and before the `cards` loop, gather accounts:

```python
    accounts = accounts_by_platform(org) if org else {}
    houses = list(org.workspaces.filter(is_archived=False)) if org else []
```

Add `accounts` to each card dict in the loop:

```python
        cards.append({
            "platform": platform,
            "label": spec["label"],
            "help": spec["help"],
            "fields": spec["fields"],
            "is_configured": state.get("is_configured", False),
            "masked": state.get("masked", {}),
            "accounts": accounts.get(platform, []),
        })
```

And add `houses` to the render context (find the `return render(request, "credentials/list.html", {...})` and add the key):

```python
        "houses": houses,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/credentials/tests/test_account_hub.py -p no:warnings -q`
Expected: PASS once the template (Task 3) renders accounts. If running before Task 3, the
account name won't appear yet — implement Task 3 in the same change set, then this passes.

- [ ] **Step 5: Commit**

```bash
git add apps/credentials/views.py
git commit -m "feat(credentials): attach org-wide accounts + houses to the credentials hub context"
```

---

## Task 3: Connected-accounts section in the template

**Files:**
- Modify: `templates/credentials/list.html`
- Test: `apps/credentials/tests/test_account_hub.py` (add delete-URL + multi-account assertions)

- [ ] **Step 1: Write the failing test**

Append to `apps/credentials/tests/test_account_hub.py`:

```python
@pytest.mark.django_db
def test_hub_renders_two_same_platform_accounts_with_delete_urls(client, org_owner, organization):
    from apps.workspaces.models import Workspace
    from apps.social_accounts.models import SocialAccount
    from django.urls import reverse
    ws = Workspace.objects.create(organization=organization, name="WAIIS")
    a1 = SocialAccount.objects.create(workspace=ws, platform="linkedin_personal",
        account_platform_id="li-a", account_name="Acct One")
    a2 = SocialAccount.objects.create(workspace=ws, platform="linkedin_personal",
        account_platform_id="li-b", account_name="Acct Two")
    client.force_login(org_owner)
    resp = client.get(reverse("credentials:list"))
    body = resp.content.decode()
    assert "Acct One" in body and "Acct Two" in body          # both accounts shown
    # each has a disconnect URL targeting its own id
    assert reverse("social_accounts:disconnect", args=[ws.id, a1.id]) in body
    assert reverse("social_accounts:disconnect", args=[ws.id, a2.id]) in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/credentials/tests/test_account_hub.py::test_hub_renders_two_same_platform_accounts_with_delete_urls -p no:warnings -q`
Expected: FAIL — disconnect URLs not present.

- [ ] **Step 3: Add the connected-accounts section to each card**

In `templates/credentials/list.html`, find the end of each card's app-key `<form>` (the
`</form>` that closes the save form, before the card's closing `</div>`). Immediately after
that `</form>`, insert the connected-accounts block:

```html
      {# ── Connected accounts for this platform ───────────────────────── #}
      <div class="border-t border-gray-100 px-5 py-4" x-data="{}">
        <div class="flex items-center justify-between mb-2">
          <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">Connected accounts</h4>
        </div>
        {% for row in card.accounts %}
        <div class="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0">
          <div class="flex items-center gap-2 min-w-0">
            {% if row.account.avatar_url and row.account.avatar_url|slice:":4" == "http" %}
            <img src="{{ row.account.avatar_url }}" alt="" class="w-6 h-6 rounded-full object-cover">
            {% else %}
            <div class="w-6 h-6 rounded-full bg-stone-200 flex items-center justify-center text-[10px] font-semibold text-stone-500">{{ row.account.account_name|make_list|first|upper }}</div>
            {% endif %}
            <span class="text-sm text-gray-800 truncate">{{ row.account.account_name }}</span>
            <span class="rounded bg-stone-100 text-stone-600 px-1.5 py-0.5 text-[10px]">{{ row.house }}</span>
            {% if row.account.needs_reconnect %}
            <span class="rounded bg-amber-100 text-amber-800 px-1.5 py-0.5 text-[10px]">reconnect</span>
            {% endif %}
          </div>
          {% if can_manage %}
          <div class="flex items-center gap-2">
            <a href="{% url 'social_accounts:reconnect' workspace_id=row.workspace_id account_id=row.account.id %}"
               class="text-xs text-blue-600 hover:text-blue-800">Reconnect</a>
            <form method="post" action="{% url 'social_accounts:disconnect' workspace_id=row.workspace_id account_id=row.account.id %}"
                  hx-confirm="Delete {{ row.account.account_name }} ({{ row.house }})? This removes the connection.">
              {% csrf_token %}
              <button type="submit" class="text-xs text-red-500 hover:text-red-700">Delete</button>
            </form>
          </div>
          {% endif %}
        </div>
        {% empty %}
        <p class="text-xs text-gray-400">No accounts connected yet.</p>
        {% endfor %}

        {% if can_manage and card.is_configured and houses %}
        <div class="mt-3" x-data="{ ws: '' }">
          <label class="text-xs text-gray-500">Connect another:</label>
          <select x-model="ws"
                  @change="if (ws) window.location = '/social-accounts/' + ws + '/connect/'"
                  class="rounded border border-gray-300 px-2 py-1 text-xs ml-1">
            <option value="">Choose house…</option>
            {% for h in houses %}<option value="{{ h.id }}">{{ h.name }}</option>{% endfor %}
          </select>
        </div>
        {% endif %}
      </div>
```

- [ ] **Step 4: Fix the CSP-unsafe inline confirm on the app-key Remove form**

The existing app-key Remove form uses `onsubmit="return confirm(...)"` (inline handler — blocked
by CSP). Replace it with `hx-confirm`. Find:

```html
      <form method="post" action="{% url 'credentials:delete' card.platform %}" onsubmit="return confirm('Remove these credentials? The channel will lock again.');">
```

Replace with:

```html
      <form method="post" action="{% url 'credentials:delete' card.platform %}" hx-confirm="Remove these credentials? The channel will lock again.">
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/credentials/tests/ -p no:warnings -q`
Expected: PASS (account_hub + existing credential save tests).

- [ ] **Step 6: Verify templates load**

Run:
```bash
DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run python -c "import django; django.setup(); from django.template.loader import get_template; get_template('credentials/list.html'); print('OK')"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add templates/credentials/list.html apps/credentials/tests/test_account_hub.py
git commit -m "feat(credentials): per-platform connected-accounts section — multi-account, delete-each, connect-another (CSP-safe)"
```

---

## Task 4: Full suite + deploy verification

**Files:** none (verification).

- [ ] **Step 1: Full suite**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest -p no:warnings -q 2>&1 | tail -8`
Expected: all pass.

- [ ] **Step 2: Push**

```bash
git push origin main
```

- [ ] **Step 3: Deploy**

```bash
railway link --project 2ee08478-c28d-4e6e-a1d0-bf8d5c871051
railway up --service web
```

- [ ] **Step 4: Verify live**

```bash
until [ "$(curl -s -o /dev/null -w '%{http_code}' https://web-production-2f84d.up.railway.app/credentials/)" != "000" ]; do sleep 8; done
curl -s -o /dev/null -w "credentials:%{http_code}\n" https://web-production-2f84d.up.railway.app/credentials/
```
Expected: `302` (redirect to login = route exists).

- [ ] **Step 5: Commit verification note**

```bash
git commit --allow-empty -m "chore: accounts & credentials hub deployed + verified"
git push origin main
```

---

## Notes for the Operator

- `/credentials/` now shows, per platform: the app key (save/remove) AND every connected
  account across all houses — each with a house badge, Reconnect, and Delete.
- "Connect another" lets you pick a house and connect a 2nd (or 3rd) account of the same
  platform — multiple LinkedIn / Instagram accounts are fully supported and persistent.
- App keys and account tokens are stored encrypted and persist permanently.
