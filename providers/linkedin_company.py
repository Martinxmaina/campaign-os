"""LinkedIn provider variant for Company Page posting.

Uses the Community Management API app with organization scopes. Posts to
Company Pages the authenticated member administers via
``w_organization_social`` and ``rw_organization_admin``.
"""

from __future__ import annotations

from .linkedin import LinkedInProvider


class LinkedInCompanyProvider(LinkedInProvider):
    """LinkedIn provider scoped to Company Page posting."""

    @property
    def platform_name(self) -> str:
        return "LinkedIn (Company Page)"

    @property
    def required_scopes(self) -> list[str]:
        return [
            "r_basicprofile",
            "w_member_social",
            "w_organization_social",
            "r_organization_social",
            "rw_organization_admin",
        ]
