import pytest
from datetime import datetime, timezone as _tz
from apps.content_intake.models import ContentIntake
from apps.content_intake.intake_calendar import schedule_intake_item
from apps.composer.models import Post


@pytest.mark.django_db
def test_schedule_creates_and_links_post(workspace, org_owner):
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="C-1", pillar_theme="Energy", angle="Solar story",
        proof_point="IEA", sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
    )
    when = datetime(2026, 7, 1, 9, 0, tzinfo=_tz.utc)
    post = schedule_intake_item(item, when, org_owner)
    assert isinstance(post, Post)
    assert post.scheduled_at == when
    item.refresh_from_db()
    assert item.post_id == post.pk
    assert item.status == ContentIntake.Status.SCHEDULED


@pytest.mark.django_db
def test_schedule_skips_blocked_item(workspace, org_owner):
    from apps.content_intake.models import UnblockCondition
    item = ContentIntake.objects.create(
        workspace=workspace, external_id="C-2", angle="x",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE, status=ContentIntake.Status.ACCEPTED,
    )
    UnblockCondition.objects.create(intake=item, condition_type="legal_milestone",
        description="MoU pending", status="open")
    when = datetime(2026, 7, 1, 9, 0, tzinfo=_tz.utc)
    assert schedule_intake_item(item, when, org_owner) is None
    item.refresh_from_db()
    assert item.post_id is None
