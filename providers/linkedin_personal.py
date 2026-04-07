"""LinkedIn provider variant for personal profile posting.

Uses the Community Management API app with personal member scopes.
Posts to the authenticated member's own profile via ``w_member_social``.
"""

from __future__ import annotations

from .linkedin import LinkedInProvider


class LinkedInPersonalProvider(LinkedInProvider):
    """LinkedIn provider scoped to personal member posting."""

    @property
    def platform_name(self) -> str:
        return "LinkedIn (Personal)"

    @property
    def required_scopes(self) -> list[str]:
        return [
            "r_basicprofile",
            "w_member_social",
            "r_member_social",
        ]
