"""Task 1 — Content Studio segmentation on Post.

Covers:
- Post gains track / pillar / campaign fields (blank-ok, choices from the
  shared taxonomy: track core/ai10bn/waiis/programs; pillar
  energy/agribusiness/ai/digital/minerals).
- apps/composer/segments.py choice sets + normalizers (reusing the intake
  sector_map for pillar normalization).
- The composer save persists track/pillar/campaign edits.
- backfill_post_segments populates those fields from intake_source (idempotent).
"""
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


# ---------------------------------------------------------------------------
# segments.py — choice sets + normalizers
# ---------------------------------------------------------------------------


def test_track_choices_are_the_canonical_four():
    from apps.composer.segments import TRACK_CHOICES

    values = [c[0] for c in TRACK_CHOICES]
    assert values == ["core", "ai10bn", "waiis", "programs"]


def test_pillar_choices_match_owner_routing_sectors():
    from apps.composer.segments import PILLAR_CHOICES

    values = {c[0] for c in PILLAR_CHOICES}
    assert values == {"energy", "agribusiness", "ai", "digital", "minerals"}


def test_normalize_pillar_uses_sector_map():
    from apps.composer.segments import normalize_pillar

    # Reuses the intake sector_map: "AI for Agriculture" -> ai (ai wins).
    assert normalize_pillar("AI for Agriculture") == "ai"
    assert normalize_pillar("Solar power access") == "energy"
    assert normalize_pillar("Smallholder farming") == "agribusiness"
    # A pillar that already names a canonical sector passes through.
    assert normalize_pillar("digital") == "digital"
    assert normalize_pillar("Minerals & mining") == "minerals"
    # Unknown / empty -> blank (editable later), never an invalid choice.
    assert normalize_pillar("") == ""
    assert normalize_pillar("Something unrelated") == ""


def test_infer_track_returns_blank_or_canonical():
    from apps.composer.segments import infer_track

    # ai10bn / $10bn signal.
    assert infer_track("AI $10bn convening") == "ai10bn"
    # WAIIS signal.
    assert infer_track("WAIIS launch") == "waiis"
    # No signal -> blank, editable later.
    assert infer_track("Generic announcement") == ""


# ---------------------------------------------------------------------------
# Post model fields
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(db):
    org = Organization.objects.create(name="AfCEN Seg")
    return Workspace.objects.create(organization=org, name="WAIIS")


@pytest.mark.django_db
def test_post_has_segment_fields_blank_ok(workspace):
    post = Post.objects.create(workspace=workspace, title="t", caption="c")
    # Blank by default — all three are optional.
    assert post.track == ""
    assert post.pillar == ""
    assert post.campaign == ""


@pytest.mark.django_db
def test_post_accepts_canonical_segment_values(workspace):
    post = Post.objects.create(
        workspace=workspace, title="t", caption="c",
        track="ai10bn", pillar="ai", campaign="EGM 2026",
    )
    post.refresh_from_db()
    assert post.track == "ai10bn"
    assert post.pillar == "ai"
    assert post.campaign == "EGM 2026"


@pytest.mark.django_db
def test_track_choices_exposed_on_field(workspace):
    field = Post._meta.get_field("track")
    assert [c[0] for c in field.choices] == ["core", "ai10bn", "waiis", "programs"]
    pillar_field = Post._meta.get_field("pillar")
    assert {c[0] for c in pillar_field.choices} == {
        "energy", "agribusiness", "ai", "digital", "minerals",
    }


# ---------------------------------------------------------------------------
# Composer save persists segment edits
# ---------------------------------------------------------------------------


class ComposerSavesSegmentsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="testpass123",
            tos_accepted_at=timezone.now(),
        )
        self.org = Organization.objects.create(name="Seg Org")
        self.workspace = Workspace.objects.create(organization=self.org, name="Seg WS")
        OrgMembership.objects.create(
            user=self.user, organization=self.org,
            org_role=OrgMembership.OrgRole.OWNER,
        )
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
        )
        self.client.force_login(self.user)
        self.save_url = reverse(
            "composer:save_post", kwargs={"workspace_id": self.workspace.id}
        )

    def test_save_persists_track_pillar_campaign(self):
        resp = self.client.post(self.save_url, data={
            "action": "save_draft",
            "title": "Seg post",
            "caption": "body",
            "tags": "",
            "track": "waiis",
            "pillar": "energy",
            "campaign": "Phase 1",
        })
        self.assertIn(resp.status_code, (200, 204, 302))
        post = Post.objects.filter(workspace=self.workspace).order_by("-created_at").first()
        self.assertIsNotNone(post)
        self.assertEqual(post.track, "waiis")
        self.assertEqual(post.pillar, "energy")
        self.assertEqual(post.campaign, "Phase 1")

    def test_save_ignores_invalid_track(self):
        resp = self.client.post(self.save_url, data={
            "action": "save_draft",
            "title": "Seg post 2",
            "caption": "body",
            "tags": "",
            "track": "not-a-track",
        })
        self.assertIn(resp.status_code, (200, 204, 302))
        post = Post.objects.filter(workspace=self.workspace).order_by("-created_at").first()
        # Invalid choice is dropped to blank rather than persisted.
        self.assertEqual(post.track, "")


# ---------------------------------------------------------------------------
# backfill_post_segments management command
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_backfill_populates_segments_from_intake(workspace):
    from apps.content_intake.models import ContentIntake

    post = Post.objects.create(workspace=workspace, title="t", caption="c")
    ContentIntake.objects.create(
        workspace=workspace, external_id="BF-1",
        pillar_theme="Solar power access", campaign="EGM 2026",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING, post=post,
    )

    out = StringIO()
    call_command("backfill_post_segments", stdout=out)
    post.refresh_from_db()
    assert post.pillar == "energy"
    assert post.campaign == "EGM 2026"

    # Idempotent — a second run is a no-op and does not crash / overwrite.
    call_command("backfill_post_segments", stdout=out)
    post.refresh_from_db()
    assert post.pillar == "energy"
    assert post.campaign == "EGM 2026"


@pytest.mark.django_db
def test_backfill_does_not_clobber_existing_values(workspace):
    from apps.content_intake.models import ContentIntake

    post = Post.objects.create(
        workspace=workspace, title="t", caption="c",
        pillar="ai", campaign="Manual",
    )
    ContentIntake.objects.create(
        workspace=workspace, external_id="BF-2",
        pillar_theme="Solar power access", campaign="Different",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.DRAFTING, post=post,
    )
    call_command("backfill_post_segments", stdout=StringIO())
    post.refresh_from_db()
    # Already-set values are preserved (idempotent, non-destructive).
    assert post.pillar == "ai"
    assert post.campaign == "Manual"
