"""LinkedIn provider variant for Company Page posting.

Lists organizations the authenticated member administers, lets the user
pick one, and publishes to that Company Page via the organization URN.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .exceptions import APIError, PublishError
from .linkedin import API_BASE, LINKEDIN_HEADERS, LinkedInProvider, _encode_urn
from .types import AccountMetrics

logger = logging.getLogger(__name__)


class LinkedInCompanyProvider(LinkedInProvider):
    """LinkedIn provider scoped to Company Page posting."""

    # The follower count returned by networkSizes is a lifetime total, not a
    # per-day delta — so the sync layer must not replay it into past dates as
    # if they were historical observations (same semantics as TikTok/Ghost).
    account_metrics_supports_date_range = False

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

    def get_user_pages(self, access_token: str) -> list[dict]:
        resp = self._request(
            "GET",
            f"{API_BASE}/v2/organizationalEntityAcls"
            "?q=roleAssignee&role=ADMINISTRATOR"
            "&projection=(elements*(organizationalTarget~(id,localizedName,vanityName,logoV2(original~:playableStreams))))",
            access_token=access_token,
            headers=LINKEDIN_HEADERS,
        )
        data = resp.json()
        pages: list[dict] = []
        for element in data.get("elements", []):
            org = element.get("organizationalTarget~", {})
            org_urn = element.get("organizationalTarget", "")
            org_id = org_urn.split(":")[-1] if org_urn else org.get("id", "")
            logo_url = None
            logo = org.get("logoV2", {}).get("original~", {})
            elements = logo.get("elements", [])
            if elements:
                identifiers = elements[0].get("identifiers", [])
                if identifiers:
                    logo_url = identifiers[0].get("identifier")
            pages.append(
                {
                    "id": str(org_id),
                    "name": org.get("localizedName", ""),
                    "handle": org.get("vanityName", ""),
                    "access_token": access_token,
                    "picture": logo_url,
                }
            )
        return pages

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def _org_urn(self) -> str:
        """Build the organization URN from the connected account's id.

        The analytics sync injects the SocialAccount's ``account_platform_id``
        (the org's numeric id) into the provider credentials. Accept a few key
        spellings, and tolerate a value that already carries the URN prefix.
        """
        raw = (
            self.credentials.get("account_platform_id")
            or self.credentials.get("org_id")
            or self.credentials.get("org_urn")
            or ""
        )
        raw = str(raw).strip()
        if not raw:
            return ""
        if raw.startswith("urn:li:organization:"):
            return raw
        return f"urn:li:organization:{raw}"

    def get_account_metrics(self, access_token: str, date_range: tuple[datetime, datetime]) -> AccountMetrics:
        """Fetch the Company Page follower count via the REST networkSizes API.

        ``GET /rest/networkSizes/{orgURN}?edgeType=COMPANY_FOLLOWED_BY_MEMBER``
        returns the lifetime follower total under ``firstDegreeSize``. This
        endpoint is scope-gated: it needs ``r_organization_social`` /
        ``rw_organization_admin`` on the token, so it only lights up once the
        LinkedIn app has org-read scope. On a 403 (token missing those scopes)
        we raise an error the analytics sync recognizes as insufficient-scope
        (``apps/analytics/tasks._is_insufficient_scope``), so the account is
        flagged ``analytics_needs_reconnect`` rather than crashing the sync.

        The follower count is a lifetime snapshot (no ``date_range`` filter),
        hence ``account_metrics_supports_date_range = False``.
        """
        org_urn = self._org_urn()
        if not org_urn:
            raise PublishError(
                "LinkedIn Company analytics requires the organization id "
                "(account_platform_id) on the connected account",
                platform=self.platform_name,
            )

        try:
            resp = self._request(
                "GET",
                f"{API_BASE}/rest/networkSizes/{_encode_urn(org_urn)}",
                access_token=access_token,
                headers=LINKEDIN_HEADERS,
                params={"edgeType": "COMPANY_FOLLOWED_BY_MEMBER"},
            )
        except APIError as exc:
            status = getattr(exc, "status_code", None)
            if status == 403:
                raise PublishError(
                    f"LinkedIn Company follower analytics needs org-read scope "
                    f"(r_organization_social / rw_organization_admin); the token "
                    f"lacks permission for {org_urn}: {exc}",
                    platform=self.platform_name,
                    raw_response=getattr(exc, "raw_response", {}),
                ) from exc
            raise PublishError(
                f"Failed to fetch LinkedIn Company follower count for {org_urn}: {exc}",
                platform=self.platform_name,
                raw_response=getattr(exc, "raw_response", {}),
            ) from exc

        data = resp.json()
        followers = data.get("firstDegreeSize", 0) or 0
        return AccountMetrics(
            followers=followers,
            extra={"raw_network_sizes": data, "org_urn": org_urn},
        )
