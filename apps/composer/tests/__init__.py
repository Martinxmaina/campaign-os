"""Tests for the Post Composer app (T-1A.1)."""

from django.test import TestCase
from django.utils import timezone

from apps.composer.models import PlatformPost, Post, PostVersion


class PostModelTest(TestCase):
    """Test the Post model and its state machine."""

    def _make_post(self, **kwargs):
        """Helper to create a Post with minimal required fields."""
        defaults = {
            "caption": "Test caption",
            "status": Post.Status.DRAFT,
        }
        defaults.update(kwargs)
        # We need a workspace; create inline without FK for unit testing
        return Post(**defaults)

    def test_valid_transitions_from_draft(self):
        post = self._make_post()
        self.assertTrue(post.can_transition_to("pending_review"))
        self.assertTrue(post.can_transition_to("scheduled"))
        self.assertTrue(post.can_transition_to("publishing"))
        self.assertFalse(post.can_transition_to("published"))
        self.assertFalse(post.can_transition_to("failed"))

    def test_valid_transitions_from_scheduled(self):
        post = self._make_post(status="scheduled")
        self.assertTrue(post.can_transition_to("publishing"))
        self.assertTrue(post.can_transition_to("draft"))
        self.assertFalse(post.can_transition_to("published"))

    def test_valid_transitions_from_publishing(self):
        post = self._make_post(status="publishing")
        self.assertTrue(post.can_transition_to("published"))
        self.assertTrue(post.can_transition_to("partially_published"))
        self.assertTrue(post.can_transition_to("failed"))
        self.assertFalse(post.can_transition_to("draft"))

    def test_transition_to_invalid_raises(self):
        post = self._make_post(status="draft")
        with self.assertRaises(ValueError) as ctx:
            post.transition_to("published")
        self.assertIn("Invalid status transition", str(ctx.exception))

    def test_transition_to_published_sets_published_at(self):
        post = self._make_post(status="publishing")
        before = timezone.now()
        post.transition_to("published")
        self.assertEqual(post.status, "published")
        self.assertIsNotNone(post.published_at)
        self.assertGreaterEqual(post.published_at, before)

    def test_is_editable(self):
        for status in ("draft", "changes_requested", "rejected", "approved", "scheduled"):
            post = self._make_post(status=status)
            self.assertTrue(post.is_editable, f"{status} should be editable")

        for status in ("publishing", "published", "failed"):
            post = self._make_post(status=status)
            self.assertFalse(post.is_editable, f"{status} should not be editable")

    def test_is_schedulable(self):
        self.assertTrue(self._make_post(status="draft").is_schedulable)
        self.assertTrue(self._make_post(status="approved").is_schedulable)
        self.assertFalse(self._make_post(status="published").is_schedulable)

    def test_caption_snippet_short(self):
        post = self._make_post(caption="Hello world")
        self.assertEqual(post.caption_snippet, "Hello world")

    def test_caption_snippet_long(self):
        long_caption = "A" * 200
        post = self._make_post(caption=long_caption)
        self.assertEqual(len(post.caption_snippet), 101)  # 100 + ellipsis char
        self.assertTrue(post.caption_snippet.endswith("…"))

    def test_status_color(self):
        post = self._make_post(status="draft")
        self.assertEqual(post.status_color, "gray")
        post.status = "published"
        self.assertEqual(post.status_color, "green")
        post.status = "failed"
        self.assertEqual(post.status_color, "red")

    def test_str_representation(self):
        post = self._make_post(caption="My awesome post about Django")
        s = str(post)
        self.assertIn("draft", s)
        self.assertIn("My awesome post about Django", s)


class PlatformPostModelTest(TestCase):
    """Test PlatformPost effective values and properties."""

    def test_effective_caption_falls_back(self):
        """When no override, effective_caption returns base post caption."""
        pp = PlatformPost()
        pp.platform_specific_caption = None
        # Use a real Post instance (unsaved) to satisfy FK descriptor
        post = Post(caption="Base caption")
        pp.post = post
        self.assertEqual(pp.effective_caption, "Base caption")

    def test_effective_caption_uses_override(self):
        pp = PlatformPost()
        pp.platform_specific_caption = "Override caption"
        post = Post(caption="Base caption")
        pp.post = post
        self.assertEqual(pp.effective_caption, "Override caption")

    def test_effective_first_comment_falls_back(self):
        pp = PlatformPost()
        pp.platform_specific_first_comment = None
        post = Post(first_comment="Base comment")
        pp.post = post
        self.assertEqual(pp.effective_first_comment, "Base comment")


class PostVersionModelTest(TestCase):
    """Test PostVersion snapshot model."""

    def test_str_representation(self):
        import uuid

        pv = PostVersion()
        pv.version_number = 3
        pv.post_id = uuid.uuid4()
        s = str(pv)
        self.assertIn("v3", s)
