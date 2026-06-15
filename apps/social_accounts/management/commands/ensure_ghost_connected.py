"""Auto-connect Ghost from the env Admin API key on boot.

Ghost auth is a single org-level Admin API key (no per-user OAuth), so when
``GHOST_ADMIN_API_KEY`` is configured we can attach a connected Ghost
SocialAccount without anyone clicking "Connect" in the UI. Mirrors
``apps.credentials.views.connect_ghost``: resolve env creds, validate via
get_profile, attach to the org's oldest workspace, update_or_create so it's
idempotent.

Run on the web role after migrate (see docker-entrypoint.sh). Safe to run
repeatedly and safe when no env key / no workspace exists (no-op, no crash).
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace
from providers import get_provider


def _ghost_env_credentials() -> dict:
    return dict(
        (getattr(settings, "PLATFORM_CREDENTIALS_FROM_ENV", {}) or {}).get("ghost", {}) or {}
    )


class Command(BaseCommand):
    help = "Idempotently connect Ghost from GHOST_ADMIN_API_KEY (env), if configured."

    def handle(self, *args, **options):
        creds = _ghost_env_credentials()
        if not creds.get("admin_api_key"):
            self.stdout.write("ensure_ghost_connected: no GHOST_ADMIN_API_KEY env creds; skipping.")
            return

        ws = Workspace.objects.order_by("created_at").first()
        if ws is None:
            self.stdout.write("ensure_ghost_connected: no workspace yet; skipping.")
            return

        try:
            profile = get_provider("ghost", dict(creds)).get_profile("")
        except Exception as exc:  # noqa: BLE001
            # Never crash boot on a Ghost validation hiccup.
            self.stderr.write(f"ensure_ghost_connected: Ghost validation failed: {exc}")
            return

        _account, created = SocialAccount.objects.update_or_create(
            workspace=ws,
            platform="ghost",
            account_platform_id=profile.platform_id,
            defaults={
                "account_name": profile.name,
                "connection_status": SocialAccount.ConnectionStatus.CONNECTED,
            },
        )
        verb = "connected" if created else "refreshed"
        self.stdout.write(f"ensure_ghost_connected: {verb} Ghost ({profile.name}).")
