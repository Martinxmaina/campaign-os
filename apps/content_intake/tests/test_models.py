"""Tests for ContentIntake, UnblockCondition, and IntakeReviewItem models."""

import pytest
from django.db.models import Count, Q

from apps.content_intake.models import ContentIntake, IntakeReviewItem, UnblockCondition


@pytest.mark.django_db
def test_intake_with_open_conditions_is_not_schedulable(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-001",
        pillar_theme="Energy",
        angle="Solar growth",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    UnblockCondition.objects.create(
        intake=intake,
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
        description="verify KALRO data",
        status=UnblockCondition.ConditionStatus.OPEN,
    )
    assert intake.is_schedulable is False


@pytest.mark.django_db
def test_private_hold_intake_is_not_schedulable(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-002",
        pillar_theme="AI",
        sensitivity=ContentIntake.Sensitivity.PRIVATE_HOLD,
        status=ContentIntake.Status.ACCEPTED,
    )
    assert intake.is_schedulable is False


@pytest.mark.django_db
def test_confidential_intake_is_not_schedulable(workspace):
    """Hard gate: sensitivity=confidential must block scheduling regardless of other fields."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-002B",
        pillar_theme="AI",
        sensitivity=ContentIntake.Sensitivity.CONFIDENTIAL,
        proof_status=ContentIntake.ProofStatus.CONFIRMED,
        status=ContentIntake.Status.ACCEPTED,
    )
    assert intake.is_schedulable is False


@pytest.mark.django_db
def test_public_safe_no_conditions_is_schedulable(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-003",
        pillar_theme="Agribusiness",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    assert intake.is_schedulable is True


@pytest.mark.django_db
def test_example_row_marked_skipped(workspace):
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-EXAMPLE",
        pillar_theme="",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.SKIPPED,
        skip_reason="example row",
    )
    assert intake.status == ContentIntake.Status.SKIPPED


# ---------------------------------------------------------------------------
# Hard gate: proof_status == NEEDS_VERIFICATION
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_needs_verification_proof_status_is_not_schedulable(workspace):
    """Second hard gate: proof_status=needs_verification blocks scheduling."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-004",
        pillar_theme="Energy",
        angle="Grid stats",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        proof_status=ContentIntake.ProofStatus.NEEDS_VERIFICATION,
        status=ContentIntake.Status.ACCEPTED,
    )
    assert intake.is_schedulable is False


# ---------------------------------------------------------------------------
# UnblockCondition: closed condition does NOT block scheduling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_closed_condition_does_not_block_scheduling(workspace):
    """A CLOSED UnblockCondition must not prevent scheduling."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-005",
        pillar_theme="AI",
        angle="Model benchmarks",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    UnblockCondition.objects.create(
        intake=intake,
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
        description="verify data",
        status=UnblockCondition.ConditionStatus.CLOSED,
    )
    assert intake.is_schedulable is True


# ---------------------------------------------------------------------------
# IntakeReviewItem: creation and resolve flow
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_intake_review_item_created_unresolved(workspace):
    """A new IntakeReviewItem starts unresolved with no resolved_by."""
    item = IntakeReviewItem.objects.create(
        workspace=workspace,
        external_id="ROW-BAD-01",
        raw_row={"pillar_theme": "", "sensitivity": "??"},
        reason=IntakeReviewItem.ReviewReason.SENSITIVITY_UNRECOGNIZED,
        detail="unrecognized value: '??'",
    )
    assert item.resolved is False
    assert item.resolved_by_id is None
    assert item.resolved_at is None


@pytest.mark.django_db
def test_intake_review_item_resolve_flow(workspace, django_user_model):
    """Marking an IntakeReviewItem resolved records the resolver and timestamp."""
    from django.utils import timezone

    reviewer = django_user_model.objects.create_user(
        email="reviewer@example.com", password="x"
    )
    item = IntakeReviewItem.objects.create(
        workspace=workspace,
        external_id="",
        raw_row={"status": "unknown"},
        reason=IntakeReviewItem.ReviewReason.STATUS_UNMAPPED,
    )

    now = timezone.now()
    item.resolved = True
    item.resolved_by = reviewer
    item.resolved_at = now
    item.save()

    item.refresh_from_db()
    assert item.resolved is True
    assert item.resolved_by == reviewer
    assert item.resolved_at == now


# ---------------------------------------------------------------------------
# OneToOneField: post field uniqueness constraint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_field_is_one_to_one(workspace):
    """A Post may only be linked to a single ContentIntake (no double-dispatch)."""
    from django.db import IntegrityError
    from apps.composer.models import Post

    post = Post.objects.create(workspace=workspace, caption="draft text")
    ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-010",
        pillar_theme="Energy",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING,
        post=post,
    )
    with pytest.raises(IntegrityError):
        ContentIntake.objects.create(
            workspace=workspace,
            external_id="ROW-011",
            pillar_theme="AI",
            sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
            status=ContentIntake.Status.DRAFTING,
            post=post,  # same Post → must fail
        )


# ---------------------------------------------------------------------------
# N+1 avoidance: has_open_conditions annotation path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_has_open_conditions_uses_annotation_when_present(workspace, django_assert_num_queries):
    """When the queryset is annotated with open_cond_count, has_open_conditions
    must not fire an extra query."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-012",
        pillar_theme="Climate",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    UnblockCondition.objects.create(
        intake=intake,
        condition_type=UnblockCondition.ConditionType.PARTNER_PERMISSION,
        description="need sign-off",
        status=UnblockCondition.ConditionStatus.OPEN,
    )

    annotated_qs = ContentIntake.objects.annotate(
        open_cond_count=Count(
            "unblock_conditions",
            filter=Q(unblock_conditions__status="open"),
        )
    )
    obj = annotated_qs.get(pk=intake.pk)

    # Accessing has_open_conditions must NOT issue any extra DB query because
    # open_cond_count is already on the instance.
    with django_assert_num_queries(0):
        assert obj.has_open_conditions is True


@pytest.mark.django_db
def test_has_open_conditions_fallback_query_without_annotation(workspace):
    """Without the annotation, has_open_conditions falls back to an EXISTS query."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-013",
        pillar_theme="Climate",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    UnblockCondition.objects.create(
        intake=intake,
        condition_type=UnblockCondition.ConditionType.SOURCE_VERIFICATION,
        description="verify",
        status=UnblockCondition.ConditionStatus.OPEN,
    )
    plain_obj = ContentIntake.objects.get(pk=intake.pk)
    assert not hasattr(plain_obj, "open_cond_count")
    assert plain_obj.has_open_conditions is True


# ---------------------------------------------------------------------------
# proof_status default is tbd (safe default for freshly imported rows)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_proof_status_defaults_to_tbd(workspace):
    """A freshly created ContentIntake must default proof_status to 'tbd', not 'confirmed',
    so that unverified rows do not accidentally pass the is_schedulable gate."""
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id="ROW-014",
        pillar_theme="Energy",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.IDEA,
    )
    assert intake.proof_status == ContentIntake.ProofStatus.TBD


@pytest.mark.django_db
def test_herald_link_fields_default_empty(workspace):
    from apps.content_intake.models import ContentIntake
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="HL-1",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    assert item.herald_content_id == ""
    assert item.herald_drafted_at is None
