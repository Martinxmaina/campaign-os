# apps/content_intake/owner_routing.py
"""Resolve the User who should review a HERALD-drafted intake item.

Priority: the sheet's named owner → the pillar's default owner → the workspace
owner/admin (fallback). All lookups are scoped to the intake's workspace members.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.content_intake.sector_map import map_pillar_to_sector

# Canonical owner per pillar/sector (sector_map normalizes pillar_theme → sector).
OWNER_BY_PILLAR = {
    "energy": "Dennis",
    "agribusiness": "Carren",
    "ai": "Joseph",
    "digital": "Nduta",
    "minerals": "Dennis",
}


def _find_member(workspace, name_or_email: str):
    """Return the workspace member matching a name/email, or None.

    Matching is deterministic and prefers the most specific signal so a bare
    first name like "Joseph" cannot be silently routed to "Josephine Other":

      1. exact email (case-insensitive) — only when the input looks like an email;
      2. exact name (case-insensitive);
      3. name substring (``icontains``) — the loose fallback.

    Each tier is scoped to this workspace's members, de-duplicated, and ordered
    by ``id`` so the result never depends on arbitrary DB row order. We stop at
    the first tier that yields a match; the email match is intentionally NOT
    OR'd into the name lookups, so ``owner_raw="Carren"`` matches a member named
    Carren and never an unrelated address that merely starts with "carren".
    """
    q = (name_or_email or "").strip()
    if not q:
        return None
    User = get_user_model()
    members = User.objects.filter(workspace_memberships__workspace=workspace)

    # 1) Exact email — only for inputs that actually look like an email address.
    if "@" in q:
        user = members.filter(email__iexact=q).order_by("id").first()
        if user:
            return user

    # 2) Exact (case-insensitive) name.
    user = members.filter(name__iexact=q).distinct().order_by("id").first()
    if user:
        return user

    # 3) Loose name substring — last resort, deterministically ordered.
    return members.filter(name__icontains=q).distinct().order_by("id").first()


def _workspace_owner(workspace):
    """Return a workspace owner/admin User, or None."""
    from apps.members.models import WorkspaceMembership
    m = (
        WorkspaceMembership.objects.filter(
            workspace=workspace, workspace_role__in=("owner", "admin")
        )
        .select_related("user")
        .order_by("workspace_role")  # 'admin' < 'owner' alphabetically; either is fine
        .first()
    )
    return m.user if m else None


def resolve_reviewer(intake):
    """Return the User to assign this intake's approval to (or None)."""
    ws = intake.workspace
    # 1) The sheet's explicit owner.
    user = _find_member(ws, intake.owner_raw)
    if user:
        return user
    # 2) The pillar's default owner.
    sector = map_pillar_to_sector(intake.pillar_theme)
    owner_name = OWNER_BY_PILLAR.get(sector)
    # Also try a direct lowercase match on the raw pillar (e.g. "digital").
    if not owner_name:
        owner_name = OWNER_BY_PILLAR.get((intake.pillar_theme or "").strip().lower())
    if owner_name:
        user = _find_member(ws, owner_name)
        if user:
            return user
    # 3) Fallback: workspace owner/admin.
    return _workspace_owner(ws)
