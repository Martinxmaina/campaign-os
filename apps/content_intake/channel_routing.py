"""Channel routing helpers for multi-channel + companion asset logic."""
from __future__ import annotations


def requires_joseph_approval(channel_targets: list[dict]) -> bool:
    """Return True if any target requires Joseph's personal approval."""
    return any(t.get("requires_joseph_approval") for t in channel_targets)


def get_nexus_brief_targets(channel_targets: list[dict]) -> list[dict]:
    """Return targets that are Nexus Brief slots."""
    return [t for t in channel_targets if t.get("platform") == "nexus_brief"]


def get_companion_assets(channel_targets: list[dict]) -> list[dict]:
    """Return companion asset specs (gated briefs, etc.)."""
    companions = []
    for t in channel_targets:
        if t.get("companion") == "gated_brief":
            companions.append({"type": "gated_brief", "lead_capture": t.get("lead_capture", False), "destination_url": t.get("destination_url", "")})
    return companions
