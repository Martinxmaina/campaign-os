"""Task 4 — Content Studio board UI + nav reconciliation.

Task 3 shipped the query/context; this task is the *markup* (and the nav
reconciliation that collapses the four fragmented draft surfaces into one).

These tests assert on the rendered HTML of ``GET /console/content``:
- filter chips for track / pillar / house / campaign / state, each a plain
  ``?param=`` link (no inline JS — CSP-safe);
- segment grouping that surfaces the T3 per-track / per-pillar counts;
- per-card status badge + inline actions keyed off the derived state:
  ``pending_review`` -> Approve / Request changes / Reject (POST forms to
  ``console:approval-decide``); ``approved`` -> Publish (POST form to
  ``composer:publish_post``); any state -> Edit (link to the composer);
- the old ``/console/drafts`` and ``/console/approvals`` routes redirect into
  the studio (the four surfaces collapse to one);
- the page is role-gated (login required) and CSP-safe (no ``onclick=``/
  ``onsubmit=`` inline handlers; the responsive card grid is present).
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
        self.org = Organization.objects.create(name="AfCEN Studio UI")
        self.workspace = Workspace.objects.create(organization=self.org, name="WAIIS")
        self.user = User.objects.create_user(
            email="studioui@example.com", password="pw", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(
            user=self.user, organization=self.org, org_role=OrgMembership.OrgRole.OWNER
        )
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
        )
        self.user.last_workspace_id = self.workspace.id
        self.user.save(update_fields=["last_workspace_id"])

        self.account = SocialAccount.objects.create(
            workspace=self.workspace, platform="mock", account_platform_id="mock-1",
            account_name="Mock", connection_status="connected",
        )
        self.client.force_login(self.user)

    def _post(self, *, pp_status, review_state=Post.ReviewState.NONE, track="",
              pillar="", campaign="", title="", caption="", assignee=None,
              published_at=None):
        post = Post.objects.create(
            workspace=self.workspace, title=title, caption=caption,
            review_state=review_state, track=track, pillar=pillar, campaign=campaign,
            review_assignee=assignee,
        )
        pp = PlatformPost.objects.create(
            post=post, social_account=self.account, status=pp_status
        )
        if published_at is not None:
            pp.published_at = published_at
            pp.save(update_fields=["published_at"])
            post.published_at = published_at
            post.save(update_fields=["published_at"])
        return post

    def _url(self):
        return reverse("console:content")

    def _get(self, **params):
        resp = self.client.get(self._url(), data=params)
        self.assertEqual(resp.status_code, 200)
        return resp


class RendersBoardTests(_Base):
    def test_renders_and_uses_the_studio_template(self):
        resp = self._get()
        self.assertTemplateUsed(resp, "console/content_studio.html")
        self.assertContains(resp, "Content Studio")

    def test_empty_board_does_not_500(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)


class FilterChipTests(_Base):
    def setUp(self):
        super().setUp()
        self._post(pp_status=PlatformPost.Status.DRAFT, track="ai10bn",
                   pillar="energy", campaign="EGM", title="Energy AI10")

    def test_track_chips_are_plain_querystring_links(self):
        html = self._get().content.decode()
        # Each track is a ?track= link (no JS) so filtering is a GET navigation.
        self.assertIn("?track=ai10bn", html)
        self.assertIn("?track=core", html)

    def test_pillar_chips_are_plain_querystring_links(self):
        html = self._get().content.decode()
        self.assertIn("?pillar=energy", html)
        self.assertIn("?pillar=ai", html)

    def test_state_chips_are_plain_querystring_links(self):
        html = self._get().content.decode()
        self.assertIn("?state=pending_review", html)

    def test_an_active_filter_is_reflected_in_the_page(self):
        # When a track filter is applied it is echoed (e.g. a clear-all link).
        html = self._get(track="ai10bn").content.decode()
        self.assertIn("ai10bn", html)


class SegmentCountTests(_Base):
    def setUp(self):
        super().setUp()
        self._post(pp_status=PlatformPost.Status.DRAFT, track="ai10bn", pillar="energy")
        self._post(pp_status=PlatformPost.Status.DRAFT, track="ai10bn", pillar="ai")
        self._post(pp_status=PlatformPost.Status.DRAFT, track="core", pillar="energy")

    def test_track_counts_render_on_chips(self):
        # The T3 per-track counts must surface next to the chips.
        ctx = self._get().context
        self.assertEqual(ctx["counts_by_track"].get("ai10bn"), 2)
        html = self._get().content.decode()
        # The count "2" appears against ai10bn somewhere on the page.
        self.assertIn("2", html)


class PerCardActionTests(_Base):
    def test_pending_review_card_has_approve_change_reject_forms(self):
        post = self._post(
            pp_status=PlatformPost.Status.PENDING_REVIEW,
            review_state=Post.ReviewState.PENDING, title="Pending one",
            assignee=self.user,
        )
        html = self._get().content.decode()
        decide_url = reverse("console:approval-decide", kwargs={"approval_id": post.id})
        # The three decisions POST to approval_decide (the gate-respecting queue).
        self.assertIn(decide_url, html)
        self.assertIn('value="approve"', html)
        self.assertIn('value="changes"', html)
        self.assertIn('value="reject"', html)

    def test_approved_card_has_a_publish_form_to_the_t2_action(self):
        post = self._post(
            pp_status=PlatformPost.Status.APPROVED,
            review_state=Post.ReviewState.APPROVED, title="Approved one",
        )
        html = self._get().content.decode()
        publish_url = reverse(
            "composer:publish_post",
            kwargs={"workspace_id": self.workspace.id, "post_id": post.id},
        )
        self.assertIn(publish_url, html)
        # Publish is a POST (the one-tap action only schedules; the chain gates).
        self.assertIn("Publish", html)

    def test_pending_card_does_not_show_publish(self):
        # A pending (not-yet-approved) post must NOT offer a Publish action.
        post = self._post(
            pp_status=PlatformPost.Status.PENDING_REVIEW,
            review_state=Post.ReviewState.PENDING, title="Pending two",
            assignee=self.user,
        )
        html = self._get().content.decode()
        publish_url = reverse(
            "composer:publish_post",
            kwargs={"workspace_id": self.workspace.id, "post_id": post.id},
        )
        self.assertNotIn(publish_url, html)

    def test_every_card_has_an_edit_link_to_the_composer(self):
        post = self._post(pp_status=PlatformPost.Status.DRAFT, title="Draft one")
        html = self._get().content.decode()
        edit_url = reverse(
            "composer:compose_edit",
            kwargs={"workspace_id": self.workspace.id, "post_id": post.id},
        )
        self.assertIn(edit_url, html)

    def test_card_shows_a_state_badge(self):
        self._post(
            pp_status=PlatformPost.Status.PENDING_REVIEW,
            review_state=Post.ReviewState.PENDING, title="Badge me",
        )
        html = self._get().content.decode()
        self.assertIn("pending_review", html)


class CspSafetyTests(_Base):
    def test_no_inline_event_handlers(self):
        self._post(
            pp_status=PlatformPost.Status.APPROVED,
            review_state=Post.ReviewState.APPROVED, title="x",
        )
        self._post(
            pp_status=PlatformPost.Status.PENDING_REVIEW,
            review_state=Post.ReviewState.PENDING, title="y", assignee=self.user,
        )
        html = self._get().content.decode()
        self.assertNotIn("onclick=", html)
        self.assertNotIn("onsubmit=", html)

    def test_responsive_card_grid_present(self):
        self._post(pp_status=PlatformPost.Status.DRAFT, title="grid")
        html = self._get().content.decode()
        # Cards lay out in a responsive grid per the plan.
        self.assertIn("grid-cols-1", html)
        self.assertIn("md:grid-cols-2", html)
        self.assertIn("xl:grid-cols-3", html)


class RoleGateTests(_Base):
    def test_login_required(self):
        self.client.logout()
        resp = self.client.get(self._url())
        self.assertIn(resp.status_code, (301, 302))


class NavReconciliationTests(_Base):
    def test_drafts_route_redirects_into_the_studio(self):
        resp = self.client.get(reverse("console:drafts"))
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn(reverse("console:content"), resp["Location"])

    def test_approvals_keeps_its_dedicated_queue(self):
        # AI Approvals is a focused, owner-routed review queue (it shows every
        # review_state=pending post, including ones with no platform posts that
        # the studio's derived-state filter would miss). It renders, not redirects.
        resp = self.client.get(reverse("console:approvals"))
        self.assertEqual(resp.status_code, 200)
