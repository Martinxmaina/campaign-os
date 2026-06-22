"""Task 1 — intake → Post segment carry-over.

`ensure_draft_post(intake)` copies intake.campaign → Post.campaign and
normalizes intake.pillar_theme → Post.pillar via the sector map; track is set
when inferable (else blank, editable later). Works on both the content-item
path and the minimal fallback path.
"""
from unittest.mock import patch

import pytest

from apps.content_intake.models import ContentIntake
from apps.content_intake.draft_post import ensure_draft_post
from apps.composer.models import Post


def _item(workspace, **kw):
    d = dict(
        workspace=workspace, external_id="DS-1", angle="Solar growth",
        proof_point="IEA", sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING,
    )
    d.update(kw)
    return ContentIntake.objects.create(**d)


@pytest.mark.django_db
def test_carry_over_pillar_and_campaign_minimal_path(workspace):
    item = _item(
        workspace, herald_content_id="",
        pillar_theme="Solar power access", campaign="EGM 2026",
    )
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        post = ensure_draft_post(item)
    assert isinstance(post, Post)
    assert post.pillar == "energy"  # normalized via sector map
    assert post.campaign == "EGM 2026"


@pytest.mark.django_db
def test_carry_over_pillar_and_campaign_content_path(workspace):
    item = _item(
        workspace, herald_content_id="ci-9",
        pillar_theme="Smallholder farming", campaign="Harvest push",
    )
    content = {"id": "ci-9", "body": "AI body", "title": "Farm"}
    with patch("apps.content_intake.draft_post.safe_get", return_value=content):
        post = ensure_draft_post(item)
    assert post.pillar == "agribusiness"
    assert post.campaign == "Harvest push"


@pytest.mark.django_db
def test_track_inferred_when_signal_present(workspace):
    item = _item(
        workspace, herald_content_id="",
        pillar_theme="AI", campaign="AI $10bn convening",
        angle="AI $10bn convening",
    )
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        post = ensure_draft_post(item)
    assert post.track == "ai10bn"


@pytest.mark.django_db
def test_track_blank_when_not_inferable(workspace):
    item = _item(
        workspace, herald_content_id="",
        pillar_theme="Energy", campaign="Generic announcement",
        angle="Generic announcement",
    )
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        post = ensure_draft_post(item)
    assert post.track == ""  # editable later


@pytest.mark.django_db
def test_unknown_pillar_stays_blank(workspace):
    item = _item(
        workspace, herald_content_id="",
        pillar_theme="", campaign="",
    )
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        post = ensure_draft_post(item)
    assert post.pillar == ""
    assert post.campaign == ""


@pytest.mark.django_db
def test_carry_over_does_not_clobber_existing_post_segments(workspace):
    """A pre-existing linked Post that already carries segments is not overwritten."""
    post = Post.objects.create(
        workspace=workspace, title="t", caption="c",
        pillar="ai", campaign="Manual", track="core",
    )
    item = _item(
        workspace, external_id="DS-9", herald_content_id="",
        pillar_theme="Solar power access", campaign="Different", post=post,
    )
    with patch("apps.content_intake.draft_post.safe_get", return_value=None):
        out = ensure_draft_post(item)
    out.refresh_from_db()
    assert out.pillar == "ai"
    assert out.campaign == "Manual"
    assert out.track == "core"
