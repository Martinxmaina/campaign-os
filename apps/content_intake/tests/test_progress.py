"""Unified content-pipeline progress: union of created (composer Posts) and
curated (ContentIntake) content, de-duped on the OneToOne link, mapped onto one
funnel (Curated → Drafting → In review → Approved → Scheduled → Published)."""
import pytest
from django.utils import timezone

from apps.composer.models import Post
from apps.content_intake.models import ContentIntake
from apps.content_intake.progress import content_pipeline_progress


def _intake(workspace, status, ext, **kw):
    return ContentIntake.objects.create(
        workspace=workspace, external_id=ext, status=status, **kw
    )


def _post(workspace, **kw):
    return Post.objects.create(workspace=workspace, caption="c", **kw)


def _stage(result, key):
    return next(s["count"] for s in result["stages"] if s["key"] == key)


@pytest.mark.django_db
def test_empty_workspace_is_all_zero(workspace):
    r = content_pipeline_progress(workspace)
    assert r["total"] == 0
    assert r["created"] == 0
    assert r["curated"] == 0
    assert r["percent"] == 0
    assert all(s["count"] == 0 for s in r["stages"])


@pytest.mark.django_db
def test_none_workspace_is_safe(db):
    r = content_pipeline_progress(None)
    assert r["total"] == 0


@pytest.mark.django_db
def test_curated_intake_maps_onto_funnel_stages(workspace):
    _intake(workspace, ContentIntake.Status.IDEA, "i1")
    _intake(workspace, ContentIntake.Status.ACCEPTED, "i2")
    _intake(workspace, ContentIntake.Status.DRAFTING, "i3")
    _intake(workspace, ContentIntake.Status.IN_REVIEW, "i4")
    _intake(workspace, ContentIntake.Status.APPROVED, "i5")
    _intake(workspace, ContentIntake.Status.SCHEDULED, "i6")
    _intake(workspace, ContentIntake.Status.PUBLISHED, "i7")

    r = content_pipeline_progress(workspace)
    assert r["curated"] == 7
    assert r["created"] == 0
    assert r["total"] == 7
    assert _stage(r, "curated") == 2  # idea + accepted
    assert _stage(r, "drafting") == 1
    assert _stage(r, "review") == 1
    assert _stage(r, "approved") == 1
    assert _stage(r, "scheduled") == 1
    assert _stage(r, "published") == 1


@pytest.mark.django_db
def test_dead_intake_statuses_are_excluded(workspace):
    _intake(workspace, ContentIntake.Status.SKIPPED, "s1")
    _intake(workspace, ContentIntake.Status.ARCHIVED, "s2")
    _intake(workspace, ContentIntake.Status.ACCEPTED, "ok")
    r = content_pipeline_progress(workspace)
    assert r["total"] == 1  # only the accepted one
    assert r["curated"] == 1


@pytest.mark.django_db
def test_created_standalone_posts_map_onto_funnel(workspace):
    _post(workspace)  # draft (no review) → drafting
    _post(workspace, review_state=Post.ReviewState.PENDING)  # → review
    _post(workspace, review_state=Post.ReviewState.APPROVED)  # → approved
    _post(workspace, scheduled_at=timezone.now())  # → scheduled
    _post(workspace, published_at=timezone.now())  # → published

    r = content_pipeline_progress(workspace)
    assert r["created"] == 5
    assert r["curated"] == 0
    assert r["total"] == 5
    assert _stage(r, "drafting") == 1
    assert _stage(r, "review") == 1
    assert _stage(r, "approved") == 1
    assert _stage(r, "scheduled") == 1
    assert _stage(r, "published") == 1


@pytest.mark.django_db
def test_rejected_standalone_posts_are_excluded(workspace):
    _post(workspace, review_state=Post.ReviewState.REJECTED)
    _post(workspace)  # one live draft
    r = content_pipeline_progress(workspace)
    assert r["created"] == 1
    assert r["total"] == 1


@pytest.mark.django_db
def test_linked_post_is_counted_once_as_curated(workspace):
    """An intake item that became a Post must not be double-counted; it stays in
    the curated origin and takes the more-advanced of the two stages."""
    item = _intake(workspace, ContentIntake.Status.APPROVED, "linked")
    post = _post(workspace, published_at=timezone.now())  # further along
    item.post = post
    item.save(update_fields=["post"])

    r = content_pipeline_progress(workspace)
    assert r["total"] == 1            # counted once, not twice
    assert r["curated"] == 1
    assert r["created"] == 0          # the linked post is NOT a standalone create
    assert _stage(r, "published") == 1  # post (published) beats intake (approved)
    assert _stage(r, "approved") == 0


@pytest.mark.django_db
def test_percent_is_weighted_progress_through_pipeline(workspace):
    # one published (1.0) + one curated (0.0) → 50% through the pipeline
    _intake(workspace, ContentIntake.Status.PUBLISHED, "p")
    _intake(workspace, ContentIntake.Status.ACCEPTED, "c")
    r = content_pipeline_progress(workspace)
    assert r["total"] == 2
    assert r["published"] == 1
    assert r["percent"] == 50
