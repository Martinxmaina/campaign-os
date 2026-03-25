"""Tests for the Social Accounts app."""

from django.test import TestCase

from apps.social_accounts.models import SocialAccount


class SocialAccountModelTest(TestCase):
    """Test SocialAccount model properties."""

    def test_platform_char_limits(self):
        """All platforms should have character limits defined."""
        for platform, _ in SocialAccount.Platform.choices:
            self.assertIn(platform, SocialAccount.PLATFORM_CHAR_LIMITS)

    def test_char_limit_property(self):
        account = SocialAccount()
        account.platform = "instagram"
        self.assertEqual(account.char_limit, 2200)

        account.platform = "bluesky"
        self.assertEqual(account.char_limit, 300)

        account.platform = "facebook"
        self.assertEqual(account.char_limit, 63206)

    def test_platform_icon_property(self):
        account = SocialAccount()
        account.platform = "instagram"
        self.assertEqual(account.platform_icon, "ig")

        account.platform = "facebook"
        self.assertEqual(account.platform_icon, "fb")

        account.platform = "bluesky"
        self.assertEqual(account.platform_icon, "bs")

    def test_str_representation(self):
        account = SocialAccount()
        account.account_name = "Test Account"
        account.platform = "instagram"
        s = str(account)
        self.assertIn("Test Account", s)
        self.assertIn("Instagram", s)
