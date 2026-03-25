"""Tests for the Media Library app."""

from django.test import TestCase

from apps.media_library.models import MediaAsset


class MediaAssetModelTest(TestCase):
    """Test MediaAsset model properties."""

    def test_is_image(self):
        asset = MediaAsset()
        asset.media_type = MediaAsset.MediaType.IMAGE
        self.assertTrue(asset.is_image)
        self.assertFalse(asset.is_video)

    def test_is_video(self):
        asset = MediaAsset()
        asset.media_type = MediaAsset.MediaType.VIDEO
        self.assertTrue(asset.is_video)
        self.assertFalse(asset.is_image)

    def test_aspect_ratio(self):
        asset = MediaAsset()
        asset.width = 1920
        asset.height = 1080
        self.assertAlmostEqual(asset.aspect_ratio, 1.78, places=2)

    def test_aspect_ratio_none_when_no_dimensions(self):
        asset = MediaAsset()
        asset.width = 0
        asset.height = 0
        self.assertIsNone(asset.aspect_ratio)

    def test_file_size_display(self):
        asset = MediaAsset()
        asset.file_size = 1024
        self.assertIn("KB", asset.file_size_display)

        asset.file_size = 1048576
        self.assertIn("MB", asset.file_size_display)

        asset.file_size = 500
        self.assertIn("B", asset.file_size_display)

    def test_str_representation(self):
        asset = MediaAsset()
        asset.filename = "photo.jpg"
        self.assertEqual(str(asset), "photo.jpg")
