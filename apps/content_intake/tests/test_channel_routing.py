"""Tests for channel_routing helpers (T12)."""
import pytest

from apps.content_intake.channel_routing import (
    get_companion_assets,
    get_nexus_brief_targets,
    requires_joseph_approval,
)


def test_requires_joseph_approval_true():
    targets = [{"platform": "linkedin", "requires_joseph_approval": True}]
    assert requires_joseph_approval(targets) is True


def test_requires_joseph_approval_false():
    targets = [{"platform": "twitter"}, {"platform": "linkedin"}]
    assert requires_joseph_approval(targets) is False


def test_get_nexus_brief_targets_filters_correctly():
    targets = [
        {"platform": "nexus_brief", "title": "Weekly Digest"},
        {"platform": "twitter"},
        {"platform": "nexus_brief", "title": "Special Edition"},
    ]
    result = get_nexus_brief_targets(targets)
    assert len(result) == 2
    assert all(t["platform"] == "nexus_brief" for t in result)


def test_get_companion_assets_returns_gated_brief():
    targets = [
        {
            "platform": "linkedin",
            "companion": "gated_brief",
            "lead_capture": True,
            "destination_url": "https://example.com/brief",
        }
    ]
    result = get_companion_assets(targets)
    assert len(result) == 1
    assert result[0]["type"] == "gated_brief"
    assert result[0]["lead_capture"] is True
    assert result[0]["destination_url"] == "https://example.com/brief"


def test_no_companions_for_plain_post():
    targets = [{"platform": "twitter"}, {"platform": "linkedin"}]
    result = get_companion_assets(targets)
    assert result == []
