# apps/content_intake/tests/test_herald_bridge.py
from unittest.mock import patch
import pytest
from apps.content_intake.herald_bridge import build_brief, request_herald_draft
from apps.content_intake.models import ContentIntake


def _make(workspace, **kw):
    defaults = dict(
        workspace=workspace, external_id="BR-1",
        pillar_theme="Energy", angle="Solar grows fast in EA",
        proof_point="IEA 2024", target_audience="Policymakers",
        channel_targets=[{"platform": "linkedin", "account": "waiis"}],
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    defaults.update(kw)
    return ContentIntake.objects.create(**defaults)


@pytest.mark.django_db
def test_build_brief_assembles_fields(workspace):
    item = _make(workspace)
    brief = build_brief(item)
    assert "Solar grows fast" in brief
    assert "IEA 2024" in brief
    assert "Policymakers" in brief
    assert "linkedin" in brief


@pytest.mark.django_db
def test_build_brief_skips_empty_fields(workspace):
    item = _make(workspace, proof_point="", target_audience="", channel_targets=[])
    brief = build_brief(item)
    assert brief == "Solar grows fast in EA"


@pytest.mark.django_db
def test_request_draft_skips_private_hold(workspace):
    item = _make(workspace, sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD)
    with patch("apps.content_intake.herald_bridge.agent_post") as m:
        result = request_herald_draft(item)
    assert result is False
    m.assert_not_called()


@pytest.mark.django_db
def test_request_draft_skips_non_accepted(workspace):
    item = _make(workspace, status=ContentIntake.Status.IDEA)
    with patch("apps.content_intake.herald_bridge.agent_post") as m:
        assert request_herald_draft(item) is False
    m.assert_not_called()


@pytest.mark.django_db
def test_request_draft_skips_already_drafted(workspace):
    from django.utils import timezone
    item = _make(workspace, herald_drafted_at=timezone.now())
    with patch("apps.content_intake.herald_bridge.agent_post") as m:
        assert request_herald_draft(item) is False
    m.assert_not_called()


@pytest.mark.django_db
def test_request_draft_success_sets_fields(workspace):
    item = _make(workspace)
    fake = {"variant_group": "vg-1", "proposals": [{"content_id": "ci-123"}]}
    with patch("apps.content_intake.herald_bridge.agent_post", return_value=fake) as m:
        assert request_herald_draft(item) is True
    m.assert_called_once()
    item.refresh_from_db()
    assert item.herald_content_id == "ci-123"
    assert item.herald_drafted_at is not None
    assert item.status == ContentIntake.Status.DRAFTING


@pytest.mark.django_db
def test_request_draft_failure_leaves_unchanged(workspace):
    item = _make(workspace)
    with patch("apps.content_intake.herald_bridge.agent_post", side_effect=Exception("boom")):
        assert request_herald_draft(item) is False
    item.refresh_from_db()
    assert item.herald_content_id == ""
    assert item.herald_drafted_at is None
    assert item.status == ContentIntake.Status.ACCEPTED


@pytest.mark.django_db
def test_build_brief_includes_doc_sources(workspace):
    from apps.content_intake.herald_bridge import build_brief
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="D-1", angle="Solar growth",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
        reference_links=[{"title": "IEA Brief", "url": "https://docs.google.com/document/d/z", "type": "gdoc"}],
    )
    brief = build_brief(item)
    assert "IEA Brief" in brief
    assert "docs.google.com/document/d/z" in brief
