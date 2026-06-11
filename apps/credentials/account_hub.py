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
