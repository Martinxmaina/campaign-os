"""Tests for channel_routing helpers (T12)."""
import pytest

from apps.content_intake.channel_routing import (
    get_companion_assets,
    get_nexus_brief_targets,
    requires_joseph_approval,
)


def test_joseph_personal_requires_approval():
    targets = [{"platform": "linkedin", "account": "joseph", "requires_joseph_approval": True}]
    assert requires_joseph_approval(targets) is True


def test_non_joseph_does_not_require_approval():
    targets = [{"platform": "linkedin", "account": "waiis"}]
    assert requires_joseph_approval(targets) is False


def test_nexus_brief_target_detected():
    targets = [{"platform": "linkedin"}, {"platform": "nexus_brief"}]
    assert get_nexus_brief_targets(targets) == [{"platform": "nexus_brief"}]


def test_gated_brief_companion():
    targets = [{"platform": "linkedin", "companion": "gated_brief", "lead_capture": True}]
    companions = get_companion_assets(targets)
    assert any(c["type"] == "gated_brief" for c in companions)


def test_no_companions_for_plain_post():
    targets = [{"platform": "linkedin", "account": "waiis"}]
    assert get_companion_assets(targets) == []
