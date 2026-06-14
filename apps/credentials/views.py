"""In-app platform credential management.

Lets an org owner/admin store OAuth app credentials (client_id/secret or
app_id/secret) per platform directly in the UI. Saved credentials are
encrypted (EncryptedJSONField) and immediately unlock the platform's
"Connect a channel" card — no env-var / redeploy needed.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.credentials.account_hub import accounts_by_platform
from apps.credentials.models import PlatformCredential
from apps.credentials.platform_fields import (
    PLATFORM_FIELDS,
    field_keys,
    required_field_keys,
)


def _env_credentials(platform):
    """Credentials supplied via environment (settings.PLATFORM_CREDENTIALS_FROM_ENV).

    These are set as Railway env vars (e.g. GHOST_ADMIN_API_KEY) and are the
    permanent, not-in-git way to configure a platform. The publish path already
    falls back to them; the UI must too, so an env-configured platform shows as
    connected + connectable without re-entering the key.
    """
    return dict((getattr(settings, "PLATFORM_CREDENTIALS_FROM_ENV", {}) or {}).get(platform, {}) or {})


def _resolve_credentials(org, platform):
    """Resolve a platform's credentials: saved DB row first, else env fallback.

    Returns the credentials dict (empty if neither configured).
    """
    if org:
        cred = (
            PlatformCredential.objects.for_org(org.id)
            .filter(platform=platform, is_configured=True)
            .first()
        )
        if cred and cred.credentials:
            return dict(cred.credentials)
    return _env_credentials(platform)


def _get_org(request):
    org = getattr(request, "org", None)
    if org:
        return org
    membership = request.user.org_memberships.select_related("organization").first()
    return membership.organization if membership else None


def _can_manage(request, org):
    if org is None:
        return False
    membership = request.user.org_memberships.filter(organization=org).first()
    return bool(membership and membership.org_role in ("owner", "admin"))


@login_required
def credentials_list(request):
    org = _get_org(request)
    can_manage = _can_manage(request, org)

    existing = {}
    if org:
        for cred in PlatformCredential.objects.for_org(org.id):
            existing[cred.platform] = {
                "is_configured": cred.is_configured,
                "masked": cred.masked_credentials,
            }

    accounts = accounts_by_platform(org) if org else {}
    houses = list(org.workspaces.filter(is_archived=False)) if org else []

    cards = []
    for platform, spec in PLATFORM_FIELDS.items():
        state = existing.get(platform, {})
        # An env-provided key (e.g. GHOST_ADMIN_API_KEY) counts as configured even
        # with no DB row, so the card shows connected + the Connect button appears.
        env_configured = bool(_env_credentials(platform))
        cards.append({
            "platform": platform,
            "label": spec["label"],
            "help": spec["help"],
            # Normalize to (key, label, type) — the template renders all fields
            # the same way; the optional 4th tuple element (required flag) is
            # only consumed server-side by required_field_keys().
            "fields": [tuple(f[:3]) for f in spec["fields"]],
            "is_configured": state.get("is_configured", False) or env_configured,
            "configured_via_env": env_configured and not state.get("is_configured", False),
            "masked": state.get("masked", {}),
            "accounts": accounts.get(platform, []),
        })

    return render(request, "credentials/list.html", {
        "cards": cards,
        "can_manage": can_manage,
        "houses": houses,
    })


@login_required
@require_POST
def save_credential(request, platform):
    org = _get_org(request)
    if not _can_manage(request, org):
        messages.error(request, "You need org owner/admin to manage credentials.")
        return redirect("credentials:list")

    if platform not in PLATFORM_FIELDS:
        messages.error(request, "Unknown platform.")
        return redirect("credentials:list")

    keys = field_keys(platform)
    # Start from existing creds so blank fields keep their saved value on update.
    existing = PlatformCredential.objects.for_org(org.id).filter(platform=platform).first()
    creds = dict(existing.credentials) if existing and existing.credentials else {}
    for key in keys:
        val = request.POST.get(key, "").strip()
        if val:
            creds[key] = val

    # All *required* fields must be present to mark configured; optional
    # fields (e.g. Ghost's newsletter_slug) are saved when present but never
    # block configuration.
    is_configured = all(creds.get(k) for k in required_field_keys(platform))
    if not is_configured:
        messages.error(
            request,
            f"All required fields must be filled in to configure "
            f"{PLATFORM_FIELDS[platform]['label']}.",
        )
        return redirect("credentials:list")

    PlatformCredential.objects.update_or_create(
        organization=org,
        platform=platform,
        defaults={"credentials": creds, "is_configured": True},
    )
    messages.success(
        request,
        f"{PLATFORM_FIELDS[platform]['label']} credentials saved. The channel is now unlocked — "
        "go to your workspace → Connect a channel.",
    )
    return redirect("credentials:list")


@login_required
@require_POST
def connect_ghost(request):
    """Connect Ghost as a single org-level SocialAccount.

    Ghost auth is one Admin API key (no per-user OAuth), so there is exactly
    one connection per org. We validate the saved credential by fetching the
    site profile, then attach the account to the org's oldest workspace.
    Idempotent: re-running updates the same SocialAccount rather than creating
    duplicates.
    """
    org = _get_org(request)
    if not _can_manage(request, org):
        messages.error(request, "You need org owner/admin to connect channels.")
        return redirect("credentials:list")
    # DB credential row first, else the env key (GHOST_ADMIN_API_KEY) — the same
    # fallback the publish path uses, so an env-configured Ghost connects from the UI.
    creds = _resolve_credentials(org, "ghost")
    if not creds.get("admin_api_key"):
        messages.error(request, "Save Ghost credentials first (or set GHOST_ADMIN_API_KEY).")
        return redirect("credentials:list")

    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace
    from providers import get_provider

    try:
        profile = get_provider("ghost", dict(creds)).get_profile("")
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"Ghost connection failed: {exc}")
        return redirect("credentials:list")

    ws = Workspace.objects.filter(organization=org).order_by("created_at").first()
    if ws is None:
        messages.error(request, "Create a workspace first.")
        return redirect("credentials:list")

    SocialAccount.objects.update_or_create(
        workspace=ws,
        platform="ghost",
        account_platform_id=profile.platform_id,
        defaults={
            "account_name": profile.name,
            "connection_status": SocialAccount.ConnectionStatus.CONNECTED,
        },
    )
    messages.success(request, f"Connected Ghost: {profile.name}.")
    return redirect("credentials:list")


@login_required
@require_POST
def delete_credential(request, platform):
    org = _get_org(request)
    if not _can_manage(request, org):
        messages.error(request, "You need org owner/admin to manage credentials.")
        return redirect("credentials:list")
    PlatformCredential.objects.for_org(org.id).filter(platform=platform).delete()
    messages.success(request, "Credentials removed.")
    # HTMX drives the submit (hx-post) so hx-confirm fires; tell the client to
    # reload so the card state + flash message refresh. Non-HTMX falls back to redirect.
    if request.headers.get("HX-Request"):
        resp = HttpResponse(status=204)
        resp["HX-Refresh"] = "true"
        return resp
    return redirect("credentials:list")
