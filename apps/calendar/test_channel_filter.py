"""Render-smoke test for the Publish/Calendar channel filter (qf-calendar / #8).

The channel filter dropdown must list ALL connected channels in the workspace,
not just channels that happen to have posts in the current tab. A freshly
connected account with zero posts must still appear as a filter option.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class ChannelFilterListsAllConnectedChannelsTests(TestCase):
    """The channel filter must surface connected channels even with no posts."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="manager@example.com",
            password="testpass123",
            name="Manager User",
            tos_accepted_at=timezone.now(),
        )
        self.org = Organization.objects.create(name="Org QF")
        self.workspace = Workspace.objects.create(organization=self.org, name="QF Workspace")
        OrgMembership.objects.create(
            user=self.user,
            organization=self.org,
            org_role=OrgMembership.OrgRole.MEMBER,
        )
        WorkspaceMembership.objects.create(
            user=self.user,
            workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.MANAGER,
        )
        # A connected channel that has NO posts at all.
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="instagram",
            account_platform_id="ig-no-posts",
            account_name="AfCEN Instagram",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.client.force_login(self.user)

    def _url(self, **params):
        url = reverse("calendar:calendar", kwargs={"workspace_id": self.workspace.id})
        if params:
            from urllib.parse import urlencode

            url = f"{url}?{urlencode(params)}"
        return url

    def test_list_mode_channel_filter_includes_postless_connected_account(self):
        """List shell channel dropdown lists the connected, post-less account."""
        resp = self.client.get(self._url(mode="list"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # The channel <option> markup renders the account name.
        self.assertIn("AfCEN Instagram", html)
        # And carries the account id as the option value so the filter works.
        self.assertIn(f'value="{self.account.id}"', html)

    def test_calendar_mode_channel_filter_includes_postless_connected_account(self):
        """Calendar shell channel dropdown also lists the connected account."""
        resp = self.client.get(self._url(mode="calendar"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("AfCEN Instagram", html)
        self.assertIn(f'value="{self.account.id}"', html)
