"""Unit tests for the composer reporting builders."""
from __future__ import annotations

import pytest
from django.utils import timezone


@pytest.fixture
def setup(db):
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="B Org")
    ws = Workspace.objects.create(name="B WS", organization=org)
    li = SocialAccount.objects.create(
        workspace=ws, platform="linkedin", account_platform_id="li-b",
        account_name="LI", connection_status="connected",
    )
    x = SocialAccount.objects.create(
        workspace=ws, platform="x", account_platform_id="x-b",
        account_name="X", connection_status="connected",
    )
    return ws, li, x


_INTAKE_SEQ = [0]


def _post(ws, account, *, status="draft", campaign="", intake=False, **kw):
    from apps.composer.models import PlatformPost, Post

    post = Post.objects.create(workspace=ws, title=f"T-{status}", caption="c" * 200, campaign=campaign, **kw)
    if account is not None:
        PlatformPost.objects.create(post=post, social_account=account, status=status)
    if intake:
        from apps.content_intake.models import ContentIntake

        _INTAKE_SEQ[0] += 1
        ContentIntake.objects.create(
            workspace=ws, post=post, status="drafting", external_id=f"ext-{_INTAKE_SEQ[0]}"
        )
    return post


@pytest.mark.django_db
def test_content_list_filters_by_campaign(setup):
    from apps.composer.api_builders import build_content_list

    ws, li, x = setup
    _post(ws, li, campaign="EGM")
    _post(ws, li, campaign="Other")
    allowed = {li.id, x.id}
    items, has_more = build_content_list(ws, allowed, campaign="EGM")
    assert len(items) == 1
    assert items[0].campaign == "EGM"
    assert items[0].caption_preview == "c" * 160


@pytest.mark.django_db
def test_content_list_allowlist_excludes_foreign_account_posts(setup):
    from apps.composer.api_builders import build_content_list

    ws, li, x = setup
    _post(ws, li)            # visible to an li-only key
    _post(ws, x)             # NOT visible to an li-only key
    items, _ = build_content_list(ws, {li.id})
    assert len(items) == 1
    assert items[0].platforms[0].account_id == li.id


@pytest.mark.django_db
def test_content_list_pagination(setup):
    from apps.composer.api_builders import build_content_list

    ws, li, x = setup
    for _ in range(3):
        _post(ws, li)
    page1, has_more = build_content_list(ws, {li.id}, limit=2, offset=0)
    assert len(page1) == 2 and has_more is True
    page2, has_more2 = build_content_list(ws, {li.id}, limit=2, offset=2)
    assert len(page2) == 1 and has_more2 is False


@pytest.mark.django_db
def test_content_list_source_flag(setup):
    from apps.composer.api_builders import build_content_list

    ws, li, x = setup
    _post(ws, li, intake=True)
    _post(ws, li, intake=False)
    items, _ = build_content_list(ws, {li.id})
    sources = sorted(i.source for i in items)
    assert sources == ["created", "curated"]


@pytest.mark.django_db
def test_build_campaigns_groups_and_counts(setup):
    from apps.composer.api_builders import build_campaigns

    ws, li, x = setup
    _post(ws, li, campaign="EGM", status="published")
    _post(ws, li, campaign="EGM", status="draft")
    _post(ws, li, campaign="")  # blank campaign excluded

    campaigns = build_campaigns(ws, {li.id, x.id}, days=30, account_map=None)
    names = {c.name for c in campaigns}
    assert names == {"EGM"}
    egm = next(c for c in campaigns if c.name == "EGM")
    assert egm.content_count == 2
    assert egm.by_status.get("published") == 1
    assert egm.by_status.get("draft") == 1
    assert egm.platforms == ["linkedin"]
    assert egm.analytics is None  # account_map=None → analytics omitted


@pytest.mark.django_db
def test_build_content_summary_windows(setup):
    from apps.composer.api_builders import build_content_summary

    ws, li, x = setup
    _post(ws, li, status="scheduled", scheduled_at=timezone.now() + timezone.timedelta(days=2))
    _post(ws, li, status="published", published_at=timezone.now() - timezone.timedelta(days=3))
    _post(ws, li, status="published", published_at=timezone.now() - timezone.timedelta(days=90))

    summary = build_content_summary(ws, {li.id})
    assert summary["total"] == 3
    assert summary["scheduled_next_7d"] == 1
    assert summary["published_last_30d"] == 1
    assert summary["by_status"].get("scheduled") == 1
