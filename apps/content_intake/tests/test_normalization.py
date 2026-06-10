"""Tests for apps/content_intake/normalization.py.

All functions are pure — no database required.
"""

import pytest

from apps.content_intake.normalization import (
    extract_unblock_conditions,
    map_status,
    normalize_sensitivity,
    parse_channels,
)


# ===========================================================================
# normalize_sensitivity
# ===========================================================================


class TestNormalizeSensitivity:
    """≥5 cases required; each covering a distinct mapped value or edge."""

    def test_public_canonical(self):
        assert normalize_sensitivity("Public") == ("public_safe", False)

    def test_public_safe_hyphenated(self):
        assert normalize_sensitivity("Public-safe") == ("public_safe", False)

    def test_public_safe_underscore(self):
        assert normalize_sensitivity("public_safe") == ("public_safe", False)

    def test_public_all_caps(self):
        assert normalize_sensitivity("PUBLIC") == ("public_safe", False)

    def test_partner_only(self):
        assert normalize_sensitivity("partner_only") == ("partner_only", False)

    def test_partner_only_with_space(self):
        assert normalize_sensitivity("partner only") == ("partner_only", False)

    def test_confidential_exact(self):
        assert normalize_sensitivity("Confidential") == ("confidential", False)

    def test_confidential_with_suffix(self):
        assert normalize_sensitivity("Confidential — internal") == ("confidential", False)

    def test_private_exact(self):
        assert normalize_sensitivity("private") == ("private_hold", False)

    def test_private_title_case(self):
        assert normalize_sensitivity("Private") == ("private_hold", False)

    def test_private_hold_phrase(self):
        assert normalize_sensitivity("private, hold") == ("private_hold", False)

    def test_private_dont_post_until(self):
        val, flag = normalize_sensitivity("Private (don't post until MoU is signed)")
        assert val == "private_hold"
        assert flag is False

    def test_unknown_fails_closed(self):
        val, flag = normalize_sensitivity("??")
        assert val == "private_hold"
        assert flag is True

    def test_empty_string_fails_closed(self):
        val, flag = normalize_sensitivity("")
        assert val == "private_hold"
        assert flag is True

    def test_non_string_fails_closed(self):
        val, flag = normalize_sensitivity(None)  # type: ignore[arg-type]
        assert val == "private_hold"
        assert flag is True

    def test_whitespace_only_fails_closed(self):
        val, flag = normalize_sensitivity("   ")
        assert val == "private_hold"
        assert flag is True


# ===========================================================================
# parse_channels
# ===========================================================================


class TestParseChannels:
    """≥5 cases required."""

    def test_joseph_personal(self):
        result = parse_channels("Joseph personal")
        assert len(result) == 1
        ch = result[0]
        assert ch["platform"] == "linkedin"
        assert ch["account"] == "joseph"
        assert ch["requires_joseph_approval"] is True

    def test_tease_to_signal_gated_brief(self):
        result = parse_channels("tease to signal.afcen.org gated brief")
        assert len(result) == 1
        ch = result[0]
        assert ch["platform"] == "linkedin"
        assert ch["companion"] == "gated_brief"
        assert ch["lead_capture"] is True

    def test_cross_published_thought_article(self):
        result = parse_channels("Cross published thought article")
        assert len(result) == 1
        ch = result[0]
        assert ch["platform"] == "article"
        assert ch["multi_channel"] is True

    def test_linkedin_waiis_page(self):
        result = parse_channels("LinkedIn (WAIIS page)")
        assert len(result) == 1
        ch = result[0]
        assert ch["platform"] == "linkedin"
        assert ch["account"] == "waiis"

    def test_linkedin_plus_nexus_brief(self):
        result = parse_channels("LinkedIn + Nexus Brief")
        assert len(result) == 2
        platforms = [c["platform"] for c in result]
        assert "linkedin" in platforms
        assert "nexus_brief" in platforms

    def test_compound_three_tokens(self):
        result = parse_channels("LinkedIn + Nexus Brief + Joseph personal")
        assert len(result) == 3

    def test_empty_string_returns_empty(self):
        assert parse_channels("") == []

    def test_whitespace_only_returns_empty(self):
        assert parse_channels("   ") == []

    def test_non_string_returns_empty(self):
        assert parse_channels(None) == []  # type: ignore[arg-type]

    def test_generic_linkedin(self):
        result = parse_channels("LinkedIn")
        assert len(result) == 1
        assert result[0]["platform"] == "linkedin"

    def test_unknown_token_preserved(self):
        result = parse_channels("SomeOtherPlatform")
        assert len(result) == 1
        assert result[0]["platform"] == "unknown"
        assert "raw" in result[0]


# ===========================================================================
# map_status
# ===========================================================================


class TestMapStatus:
    """≥3 cases required."""

    def test_idea(self):
        assert map_status("Idea") == ("idea", False)

    def test_idea_lowercase(self):
        assert map_status("idea") == ("idea", False)

    def test_post_event_piece(self):
        assert map_status("Post event piece") == ("accepted", False)

    def test_accepted(self):
        assert map_status("accepted") == ("accepted", False)

    def test_greenlit(self):
        assert map_status("greenlit") == ("accepted", False)

    def test_draft(self):
        assert map_status("Draft") == ("drafting", False)

    def test_drafting(self):
        assert map_status("drafting") == ("drafting", False)

    def test_in_review(self):
        assert map_status("In review") == ("in_review", False)

    def test_review(self):
        assert map_status("review") == ("in_review", False)

    def test_approved(self):
        assert map_status("approved") == ("approved", False)

    def test_approval_pending(self):
        assert map_status("Approval pending") == ("approved", False)

    def test_scheduled(self):
        assert map_status("scheduled") == ("scheduled", False)

    def test_published(self):
        assert map_status("published") == ("published", False)

    def test_live(self):
        assert map_status("live") == ("published", False)

    def test_archived(self):
        assert map_status("archived") == ("archived", False)

    def test_done(self):
        assert map_status("done") == ("archived", False)

    def test_hold(self):
        assert map_status("hold") == ("held", False)

    def test_blocked(self):
        assert map_status("blocked") == ("held", False)

    def test_waiting(self):
        assert map_status("waiting on confirmation") == ("held", False)

    def test_unknown_goes_to_review_queue(self):
        val, flag = map_status("??gibberish??")
        assert val == "review_queue"
        assert flag is True

    def test_non_string_goes_to_review_queue(self):
        val, flag = map_status(None)  # type: ignore[arg-type]
        assert val == "review_queue"
        assert flag is True


# ===========================================================================
# extract_unblock_conditions
# ===========================================================================


class TestExtractUnblockConditions:
    """≥4 cases required."""

    def test_verify_source(self):
        result = extract_unblock_conditions("Need to verify source before posting")
        types = [c["type"] for c in result]
        assert "source_verification" in types

    def test_check_source(self):
        result = extract_unblock_conditions("check source for KALRO stats")
        types = [c["type"] for c in result]
        assert "source_verification" in types

    def test_mou_triggers_legal_milestone(self):
        result = extract_unblock_conditions("Hold until MoU is signed")
        types = [c["type"] for c in result]
        assert "legal_milestone" in types
        # MoU + legal_milestone should override partner_permission
        assert "partner_permission" not in types

    def test_dont_post_until(self):
        result = extract_unblock_conditions("Don't post until board approval received")
        types = [c["type"] for c in result]
        assert "legal_milestone" in types

    def test_not_until(self):
        result = extract_unblock_conditions("not until the agreement is finalized")
        types = [c["type"] for c in result]
        assert "legal_milestone" in types

    def test_hold_until(self):
        result = extract_unblock_conditions("hold until sign-off from legal")
        types = [c["type"] for c in result]
        assert "legal_milestone" in types

    def test_partner_permission(self):
        result = extract_unblock_conditions("Confirm partner is happy to share this")
        types = [c["type"] for c in result]
        assert "partner_permission" in types

    def test_kalro_partner_permission(self):
        result = extract_unblock_conditions("KALRO needs to confirm data is shareable")
        types = [c["type"] for c in result]
        assert "partner_permission" in types

    def test_figure_confirmation(self):
        result = extract_unblock_conditions("confirm the exact figure before publishing")
        types = [c["type"] for c in result]
        assert "figure_confirmation" in types

    def test_confirm_range(self):
        result = extract_unblock_conditions("confirm range with the data team")
        types = [c["type"] for c in result]
        assert "figure_confirmation" in types

    def test_confirm_stat(self):
        result = extract_unblock_conditions("Confirm the stat cited is correct")
        types = [c["type"] for c in result]
        assert "figure_confirmation" in types

    def test_no_patterns_returns_empty(self):
        result = extract_unblock_conditions("Everything looks good, proceed.")
        assert result == []

    def test_empty_string_returns_empty(self):
        assert extract_unblock_conditions("") == []

    def test_non_string_returns_empty(self):
        assert extract_unblock_conditions(None) == []  # type: ignore[arg-type]

    def test_dedup_by_type(self):
        """Duplicate patterns of the same type should only produce one entry."""
        result = extract_unblock_conditions(
            "verify source and double check source again"
        )
        types = [c["type"] for c in result]
        assert types.count("source_verification") == 1

    def test_description_preserved(self):
        notes = "verify source for this stat before posting"
        result = extract_unblock_conditions(notes)
        for cond in result:
            assert cond["description"] == notes

    def test_multiple_conditions_in_one_note(self):
        """A single complex note can produce multiple condition types."""
        notes = "verify source — and don't post until MoU signed — also confirm figure"
        result = extract_unblock_conditions(notes)
        types = {c["type"] for c in result}
        assert "source_verification" in types
        assert "legal_milestone" in types
        assert "figure_confirmation" in types
