"""Task 3 — Content Studio unified board: backend view + filtered/segmented query.

The Content Studio collapses the four fragmented draft surfaces into ONE board.
This task is the *query/context* layer behind it (the UI is Task 4): a single
``content_studio`` view at ``/console/content`` that, for the active workspace,
returns EVERY relevant post unified across states — draft, pending_review,
approved (not yet published), scheduled, published (recent) — as one list, each
card carrying a state label. It supports the filter set
``?track=&pillar=&house=&campaign=&state=&q=`` (each independently and combined),
returns per-segment counts (by track and by pillar) for the chips, respects
``for_workspace`` scoping (the cross-house wall), and never 500s on an empty DB.

These are query-shaped tests: they assert on the rendered template context, not
on markup (that is Task 4).
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class _Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="AfCEN Studio")
        self.workspace = Workspace.objects.create(organization=self.org, name="WAIIS")
        # A second house in the same org — the cross-house wall must exclude it.
        self.other_ws = Workspace.objects.create(organization=self.org, name="AfCEN")

        self.user = User.objects.create_user(
            email="studio@example.com", password="pw", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(
            user=self.user, organization=self.org, org_role=OrgMembership.OrgRole.OWNER
        )
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
        )
        # Console pages have no workspace_id in the URL; the active workspace is
        # resolved from last_workspace_id.
        self.user.last_workspace_id = self.workspace.id
        self.user.save(update_fields=["last_workspace_id"])

        self.account = SocialAccount.objects.create(
            workspace=self.workspace, platform="mock", account_platform_id="mock-1",
            account_name="Mock", connection_status="connected",
        )
        self.other_account = SocialAccount.objects.create(
            workspace=self.other_ws, platform="mock", account_platform_id="mock-2",
            account_name="Mock2", connection_status="connected",
        )
        self.client.force_login(self.user)

    # ---- helpers ---------------------------------------------------------
    def _post(self, *, pp_status, ws=None, review_state=Post.ReviewState.NONE,
              track="", pillar="", campaign="", title="", caption="", account=None,
              published_at=None):
        ws = ws or self.workspace
        account = account or (self.account if ws == self.workspace else self.other_account)
        post = Post.objects.create(
            workspace=ws, title=title, caption=caption, review_state=review_state,
            track=track, pillar=pillar, campaign=campaign,
        )
        pp = PlatformPost.objects.create(post=post, social_account=account, status=pp_status)
        if published_at is not None:
            pp.published_at = published_at
            pp.save(update_fields=["published_at"])
            post.published_at = published_at
            post.save(update_fields=["published_at"])
        return post

    def _url(self):
        return reverse("console:content")

    def _ctx(self, **params):
        resp = self.client.get(self._url(), data=params)
        self.assertEqual(resp.status_code, 200)
        return resp.context

    def _ids(self, ctx):
        return {str(p.id) for p in ctx["posts"]}


class UnifiedAcrossStatesTests(_Base):
    def test_lists_posts_across_every_relevant_state_with_a_state_label(self):
        draft = self._post(pp_status=PlatformPost.Status.DRAFT, title="draft")
        pending = self._post(
            pp_status=PlatformPost.Status.PENDING_REVIEW,
            review_state=Post.ReviewState.PENDING, title="pending",
        )
        approved = self._post(
            pp_status=PlatformPost.Status.APPROVED,
            review_state=Post.ReviewState.APPROVED, title="approved",
        )
        scheduled = self._post(pp_status=PlatformPost.Status.SCHEDULED, title="scheduled")
        published = self._post(
            pp_status=PlatformPost.Status.PUBLISHED, title="published",
            published_at=timezone.now(),
        )

        ctx = self._ctx()
        ids = self._ids(ctx)
        for p in (draft, pending, approved, scheduled, published):
            self.assertIn(str(p.id), ids)

        # Each card carries a state label (its derived status).
        for p in ctx["posts"]:
            self.assertTrue(getattr(p, "studio_state", None))

    def test_no_500_on_empty_workspace(self):
        ctx = self._ctx()
        self.assertEqual(list(ctx["posts"]), [])


class CrossHouseWallTests(_Base):
    def test_only_active_workspace_posts_are_returned(self):
        mine = self._post(pp_status=PlatformPost.Status.DRAFT, title="mine")
        theirs = self._post(
            pp_status=PlatformPost.Status.DRAFT, ws=self.other_ws, title="theirs"
        )
        ctx = self._ctx()
        ids = self._ids(ctx)
        self.assertIn(str(mine.id), ids)
        self.assertNotIn(str(theirs.id), ids)


class FilterTests(_Base):
    def setUp(self):
        super().setUp()
        self.energy_ai10 = self._post(
            pp_status=PlatformPost.Status.DRAFT, track="ai10bn", pillar="energy",
            campaign="EGM", title="Energy AI10",
        )
        self.agri_core = self._post(
            pp_status=PlatformPost.Status.PENDING_REVIEW,
            review_state=Post.ReviewState.PENDING,
            track="core", pillar="agribusiness", campaign="Harvest",
            title="Agri Core",
        )
        self.ai_waiis = self._post(
            pp_status=PlatformPost.Status.APPROVED,
            review_state=Post.ReviewState.APPROVED,
            track="waiis", pillar="ai", campaign="EGM",
            title="AI WAIIS searchable keyword",
        )

    def test_filter_by_track(self):
        ctx = self._ctx(track="ai10bn")
        self.assertEqual(self._ids(ctx), {str(self.energy_ai10.id)})

    def test_filter_by_pillar(self):
        ctx = self._ctx(pillar="agribusiness")
        self.assertEqual(self._ids(ctx), {str(self.agri_core.id)})

    def test_filter_by_campaign(self):
        ctx = self._ctx(campaign="EGM")
        self.assertEqual(
            self._ids(ctx), {str(self.energy_ai10.id), str(self.ai_waiis.id)}
        )

    def test_filter_by_state(self):
        # state filter narrows to the derived post-level state.
        ctx = self._ctx(state="pending_review")
        self.assertEqual(self._ids(ctx), {str(self.agri_core.id)})

    def test_filter_by_q_text_search(self):
        ctx = self._ctx(q="searchable keyword")
        self.assertEqual(self._ids(ctx), {str(self.ai_waiis.id)})

    def test_filters_combine(self):
        # track=waiis AND campaign=EGM → only the AI WAIIS post.
        ctx = self._ctx(track="waiis", campaign="EGM")
        self.assertEqual(self._ids(ctx), {str(self.ai_waiis.id)})

        # track=core AND campaign=EGM → nothing (agri_core is campaign Harvest).
        ctx2 = self._ctx(track="core", campaign="EGM")
        self.assertEqual(self._ids(ctx2), set())

    def test_unknown_filter_value_does_not_500_and_returns_empty(self):
        ctx = self._ctx(track="not-a-real-track")
        self.assertEqual(self._ids(ctx), set())

    def test_house_filter_other_workspace_excluded_by_wall(self):
        # The house filter never lets a different workspace's posts leak in.
        ctx = self._ctx(house=str(self.other_ws.id))
        for p in ctx["posts"]:
            self.assertEqual(p.workspace_id, self.workspace.id)


class SegmentCountsTests(_Base):
    def setUp(self):
        super().setUp()
        self._post(pp_status=PlatformPost.Status.DRAFT, track="ai10bn", pillar="energy")
        self._post(pp_status=PlatformPost.Status.DRAFT, track="ai10bn", pillar="ai")
        self._post(pp_status=PlatformPost.Status.DRAFT, track="core", pillar="energy")

    def test_counts_by_track(self):
        ctx = self._ctx()
        by_track = ctx["counts_by_track"]
        self.assertEqual(by_track.get("ai10bn"), 2)
        self.assertEqual(by_track.get("core"), 1)

    def test_counts_by_pillar(self):
        ctx = self._ctx()
        by_pillar = ctx["counts_by_pillar"]
        self.assertEqual(by_pillar.get("energy"), 2)
        self.assertEqual(by_pillar.get("ai"), 1)

    def test_counts_reflect_the_active_filter(self):
        # When filtered to ai10bn, the pillar counts only reflect ai10bn posts.
        ctx = self._ctx(track="ai10bn")
        by_pillar = ctx["counts_by_pillar"]
        self.assertEqual(by_pillar.get("energy"), 1)
        self.assertEqual(by_pillar.get("ai"), 1)
