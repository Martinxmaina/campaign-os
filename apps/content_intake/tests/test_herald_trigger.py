from unittest.mock import patch
import pytest
from apps.content_intake.models import ContentIntake, UnblockCondition
from apps.content_intake.tasks import request_herald_drafts_for_workspace


@pytest.mark.django_db
def test_drafts_only_eligible_items(workspace):
    ContentIntake.objects.create(
        workspace=workspace, external_id="A",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="a",
    )
    ContentIntake.objects.create(
        workspace=workspace, external_id="B",
        sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
        status=ContentIntake.Status.ACCEPTED, angle="b",
    )
    ContentIntake.objects.create(
        workspace=workspace, external_id="C",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.IDEA, angle="c",
    )
    with patch("apps.content_intake.tasks.request_herald_draft", return_value=True) as m:
        result = request_herald_drafts_for_workspace(str(workspace.pk))
    # Only item A is eligible (accepted + public_safe)
    assert m.call_count == 1
    assert result["drafted"] == 1


@pytest.mark.django_db
def test_is_schedulable_gate_blocks_drafting(workspace):
    """Real eligibility logic (not mocked): the is_schedulable gate must block
    drafting for accepted + public_safe items that are otherwise agent-visible.

    CLAUDE.md invariant: 'Unblock conditions block scheduling at model level.'
    proof_status=needs_verification is the other hard gate. Neither item may
    reach HERALD — request_herald_draft returns False and agent_post is never
    called.
    """
    # Eligible-looking but blocked by an OPEN unblock condition.
    blocked_by_condition = ContentIntake.objects.create(
        workspace=workspace, external_id="COND",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="cond",
        proof_status=ContentIntake.ProofStatus.CONFIRMED,
    )
    UnblockCondition.objects.create(
        intake=blocked_by_condition,
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
        description="verify the source",
        status=UnblockCondition.ConditionStatus.OPEN,
    )
    # Eligible-looking but blocked by proof_status=needs_verification.
    ContentIntake.objects.create(
        workspace=workspace, external_id="PROOF",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="proof",
        proof_status=ContentIntake.ProofStatus.NEEDS_VERIFICATION,
    )

    # NOTE: request_herald_draft is NOT mocked here — the real eligibility chain
    # (_is_eligible -> is_schedulable -> has_open_conditions) must run.
    with patch("apps.content_intake.herald_bridge.agent_post") as agent:
        result = request_herald_drafts_for_workspace(str(workspace.pk))

    agent.assert_not_called()
    assert result["drafted"] == 0

    blocked_by_condition.refresh_from_db()
    assert blocked_by_condition.herald_drafted_at is None
    assert blocked_by_condition.status == ContentIntake.Status.ACCEPTED


@pytest.mark.django_db
def test_request_herald_draft_returns_false_for_open_condition(workspace):
    """Direct unit-level proof that the gate returns False, not just that the
    sweep skips it (real is_schedulable branch, no mocking of eligibility)."""
    from apps.content_intake.herald_bridge import request_herald_draft

    item = ContentIntake.objects.create(
        workspace=workspace, external_id="DIRECT-COND",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="x",
        proof_status=ContentIntake.ProofStatus.CONFIRMED,
    )
    UnblockCondition.objects.create(
        intake=item,
        condition_type=UnblockCondition.ConditionType.PARTNER_PERMISSION,
        description="await partner sign-off",
        status=UnblockCondition.ConditionStatus.OPEN,
    )
    with patch("apps.content_intake.herald_bridge.agent_post") as agent:
        assert request_herald_draft(item) is False
    agent.assert_not_called()


@pytest.mark.django_db
def test_request_herald_draft_returns_false_for_needs_verification(workspace):
    from apps.content_intake.herald_bridge import request_herald_draft

    item = ContentIntake.objects.create(
        workspace=workspace, external_id="DIRECT-PROOF",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="x",
        proof_status=ContentIntake.ProofStatus.NEEDS_VERIFICATION,
    )
    with patch("apps.content_intake.herald_bridge.agent_post") as agent:
        assert request_herald_draft(item) is False
    agent.assert_not_called()


@pytest.mark.django_db
def test_sets_last_draft_cache(workspace):
    from django.core.cache import cache
    ContentIntake.objects.create(
        workspace=workspace, external_id="A",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED, angle="a",
    )
    with patch("apps.content_intake.tasks.request_herald_draft", return_value=True):
        request_herald_drafts_for_workspace(str(workspace.pk))
    assert cache.get(f"intake:last_draft:{workspace.pk}") is not None
