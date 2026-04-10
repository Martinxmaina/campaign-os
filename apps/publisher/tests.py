"""Tests for the Publishing Engine (T-1A.3)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.publisher.engine import MAX_RETRIES, RETRY_BACKOFF, PublishEngine
from apps.publisher.models import PublishLog, RateLimitState


class RateLimitStateModelTest(TestCase):
    """Test RateLimitState model logic."""

    def test_is_rate_limited_when_zero_remaining_and_window_active(self):
        state = RateLimitState()
        state.requests_remaining = 0
        state.window_resets_at = timezone.now() + timedelta(minutes=5)
        self.assertTrue(state.is_rate_limited)

    def test_is_not_rate_limited_when_zero_remaining_and_window_expired(self):
        state = RateLimitState()
        state.requests_remaining = 0
        state.window_resets_at = timezone.now() - timedelta(minutes=5)
        self.assertFalse(state.is_rate_limited)

    def test_is_not_rate_limited_with_remaining_requests(self):
        state = RateLimitState()
        state.requests_remaining = 50
        state.window_resets_at = timezone.now() + timedelta(minutes=5)
        self.assertFalse(state.is_rate_limited)

    def test_can_publish_when_unknown(self):
        state = RateLimitState()
        state.requests_remaining = -1
        self.assertTrue(state.can_publish)

    def test_can_publish_when_remaining(self):
        state = RateLimitState()
        state.requests_remaining = 10
        self.assertTrue(state.can_publish)

    def test_cannot_publish_when_rate_limited(self):
        state = RateLimitState()
        state.requests_remaining = 0
        state.window_resets_at = timezone.now() + timedelta(minutes=5)
        self.assertFalse(state.can_publish)


class PublishEngineTest(TestCase):
    """Test PublishEngine core logic."""

    def test_retry_backoff_schedule(self):
        """Verify retry backoff values match spec."""
        self.assertEqual(RETRY_BACKOFF, [60, 300, 1800])
        self.assertEqual(MAX_RETRIES, 3)

    def test_engine_instantiates(self):
        engine = PublishEngine()
        self.assertIsNotNone(engine)

    @patch("apps.publisher.engine.PlatformPost.objects")
    def test_get_due_platform_posts_filters_correctly(self, mock_objects):
        """Engine should query PlatformPosts with a Coalesce effective_at filter."""
        engine = PublishEngine()
        mock_qs = MagicMock()
        mock_objects.filter.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.__getitem__ = MagicMock(return_value=[])

        engine._get_due_platform_posts()

        # First filter: editorial status (now lives on PlatformPost itself)
        first_call = mock_objects.filter.call_args_list[0]
        self.assertIn("status", first_call.kwargs)
        # Second filter (on annotated qs): effective_at__lte
        second_call = mock_qs.filter.call_args_list[0]
        self.assertIn("effective_at__lte", second_call.kwargs)


class PublishLogModelTest(TestCase):
    """Test PublishLog model."""

    def test_str_representation(self):
        log = PublishLog()
        log.attempt_number = 2
        log.status_code = 200
        s = str(log)
        self.assertIn("2", s)
        self.assertIn("200", s)
