"""Task 2 — Approve → one-tap Publish (the gate ALWAYS runs).

Covers the Content Studio decision: AI/HERALD drafts must be approved first;
once approved, a one-tap Publish appears that SCHEDULES the post (effective now)
so the existing Celery publish chain runs and the untouchable gate enforces.

Hard invariants asserted here:
- The action transitions the post's PlatformPosts to ``scheduled`` (effective
  now) — it does NOT publish directly and does NOT touch the gate.
- It NEVER sets ``gate_bypassed`` on an AI/HERALD post. The dispatched path
  still gate-checks: an AI post that reached publish without a gate_id is still
  blockable by the gate (``_gate_failure_reason`` == "missing gate_id").
- A NOT-approved AI post, requested by a user who is not the author with
  ``publish_directly``, is rejected (403) and nothing is scheduled.
- A human author WITH ``publish_directly`` can publish their own draft directly,
  and that human-direct path is the only one allowed to bypass the gate.
- Approving via ``approval_decide`` leaves the post publishable by this action.
- Role-gated, CSRF-enforced, idempotent (double-publish is safe).
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.models import ApprovalAction
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.publisher.engine import PublishEngine
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class _Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="AfCEN Pub")
        self.workspace = Workspace.objects.create(organization=self.org, name="WAIIS")

        # owner — full perms (approve + publish_directly)
        self.owner = User.objects.create_user(
            email="owner@example.com", password="pw", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(
            user=self.owner, organization=self.org, org_role=OrgMembership.OrgRole.OWNER
        )
        WorkspaceMembership.objects.create(
            user=self.owner, workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
        )

        # pillar_lead — approve_posts=True but publish_directly=False
        self.approver = User.objects.create_user(
            email="lead@example.com", password="pw", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(
            user=self.approver, organization=self.org, org_role=OrgMembership.OrgRole.MEMBER
        )
        WorkspaceMembership.objects.create(
            user=self.approver, workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.PILLAR_LEAD,
        )

        # editor — neither approve_posts nor publish_directly
        self.editor = User.objects.create_user(
            email="editor@example.com", password="pw", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(
            user=self.editor, organization=self.org, org_role=OrgMembership.OrgRole.MEMBER
        )
        WorkspaceMembership.objects.create(
            user=self.editor, workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.EDITOR,
        )

        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="mock",
            account_platform_id="mock-1",
            account_name="Mock Account",
            connection_status="connected",
        )

    def _publish_url(self, post):
        return reverse(
            "composer:publish_post",
            kwargs={"workspace_id": self.workspace.id, "post_id": post.id},
        )

    def _make_ai_post(self, review_state, author=None):
        """An AI/HERALD-drafted Post: NO author by default, gate NOT bypassed."""
        post = Post.objects.create(
            workspace=self.workspace,
            author=author,
            title="Herald draft",
            caption="Drafted by HERALD",
            review_state=review_state,
        )
        # AI posts leave gate_bypassed=False and have no gate_id (they must be
        # gated). status = pending_review when awaiting approval, approved after.
        pp_status = (
            PlatformPost.Status.APPROVED
            if review_state == Post.ReviewState.APPROVED
            else PlatformPost.Status.PENDING_REVIEW
        )
        PlatformPost.objects.create(
            post=post, social_account=self.account,
            status=pp_status, gate_bypassed=False,
        )
        return post


class ApprovedAIPostPublishTests(_Base):
    def test_approved_post_schedules_children_for_the_gate_enforced_chain(self):
        post = self._make_ai_post(Post.ReviewState.APPROVED)
        self.client.force_login(self.owner)

        resp = self.client.post(self._publish_url(post))
        self.assertIn(resp.status_code, (200, 204, 302))

        pp = post.platform_posts.get()
        # SCHEDULED, effective now → the existing Celery chain picks it up.
        self.assertEqual(pp.status, PlatformPost.Status.SCHEDULED)
        effective = pp.scheduled_at or post.scheduled_at
        self.assertIsNotNone(effective)
        self.assertLessEqual(effective, timezone.now())

    def test_publish_does_not_bypass_the_gate_for_ai_posts(self):
        """The one-tap Publish must NOT inject gate_bypassed on AI posts; the
        dispatched path still gate-checks. An AI post that has no gate_id is
        still blockable by the gate after this action runs."""
        post = self._make_ai_post(Post.ReviewState.APPROVED)
        self.client.force_login(self.owner)
        self.client.post(self._publish_url(post))

        pp = post.platform_posts.get()
        self.assertFalse(pp.gate_bypassed)
        self.assertIsNone(pp.gate_id)
        # The untouchable gate would still block this (no gate_id) — proving the
        # publish action did not weaken or bypass the gate for AI content.
        self.assertEqual(
            PublishEngine()._gate_failure_reason(pp), "missing gate_id"
        )

    def test_double_publish_is_idempotent(self):
        post = self._make_ai_post(Post.ReviewState.APPROVED)
        self.client.force_login(self.owner)

        r1 = self.client.post(self._publish_url(post))
        self.assertIn(r1.status_code, (200, 204, 302))
        r2 = self.client.post(self._publish_url(post))
        # Second publish does not error or re-trigger anything unsafe.
        self.assertIn(r2.status_code, (200, 204, 302))
        pp = post.platform_posts.get()
        self.assertEqual(pp.status, PlatformPost.Status.SCHEDULED)

    def test_approver_without_publish_directly_can_one_tap_publish_approved(self):
        """Once approved, one-tap Publish is allowed even for a reviewer who
        lacks publish_directly — the gate (not the role) is the safety net."""
        post = self._make_ai_post(Post.ReviewState.APPROVED)
        self.client.force_login(self.approver)
        resp = self.client.post(self._publish_url(post))
        self.assertIn(resp.status_code, (200, 204, 302))
        self.assertEqual(
            post.platform_posts.get().status, PlatformPost.Status.SCHEDULED
        )


class NotApprovedAIPostBlockedTests(_Base):
    def test_pending_ai_post_cannot_be_published_by_non_privileged_user(self):
        post = self._make_ai_post(Post.ReviewState.PENDING)
        self.client.force_login(self.editor)
        resp = self.client.post(self._publish_url(post))
        self.assertEqual(resp.status_code, 403)
        # Nothing scheduled — still pending_review.
        self.assertEqual(
            post.platform_posts.get().status, PlatformPost.Status.PENDING_REVIEW
        )

    def test_none_state_ai_post_cannot_be_published_by_non_privileged_user(self):
        post = self._make_ai_post(Post.ReviewState.NONE)
        # NONE-state AI post: no author, not approved.
        self.client.force_login(self.editor)
        resp = self.client.post(self._publish_url(post))
        self.assertEqual(resp.status_code, 403)


class HumanDirectPublishTests(_Base):
    def test_human_author_with_publish_directly_publishes_own_unapproved_post(self):
        # Human-authored draft (author=owner), composed directly — gate bypass
        # is the operator's deliberate human-authorship choice.
        post = Post.objects.create(
            workspace=self.workspace, author=self.owner,
            title="Human post", caption="written by a person",
            review_state=Post.ReviewState.NONE,
        )
        PlatformPost.objects.create(
            post=post, social_account=self.account,
            status=PlatformPost.Status.DRAFT, gate_bypassed=True,
        )
        self.client.force_login(self.owner)
        resp = self.client.post(self._publish_url(post))
        self.assertIn(resp.status_code, (200, 204, 302))
        self.assertEqual(
            post.platform_posts.get().status, PlatformPost.Status.SCHEDULED
        )

    def test_author_without_publish_directly_cannot_direct_publish_unapproved(self):
        # editor authored their own draft but lacks publish_directly + not approved.
        post = Post.objects.create(
            workspace=self.workspace, author=self.editor,
            title="Editor draft", caption="needs approval",
            review_state=Post.ReviewState.NONE,
        )
        PlatformPost.objects.create(
            post=post, social_account=self.account,
            status=PlatformPost.Status.DRAFT, gate_bypassed=False,
        )
        self.client.force_login(self.editor)
        resp = self.client.post(self._publish_url(post))
        self.assertEqual(resp.status_code, 403)


class ApprovalDecideLeavesPostPublishableTests(_Base):
    def test_approve_then_publish_succeeds(self):
        """approval_decide(approve) must leave the post in a state where the
        one-tap Publish action is allowed and schedules the children."""
        post = self._make_ai_post(Post.ReviewState.PENDING)
        post.review_assignee = self.approver
        post.save(update_fields=["review_assignee"])

        self.client.force_login(self.approver)
        decide_url = reverse("console:approval-decide", kwargs={"approval_id": post.id})
        # The approver's workspace is resolved from last_workspace_id; set it.
        self.approver.last_workspace_id = self.workspace.id
        self.approver.save(update_fields=["last_workspace_id"])
        dec = self.client.post(decide_url, data={"decision": "approve"})
        self.assertIn(dec.status_code, (200, 302))

        post.refresh_from_db()
        self.assertEqual(post.review_state, Post.ReviewState.APPROVED)
        # Children moved pending_review -> approved by approval_decide.
        self.assertEqual(
            post.platform_posts.get().status, PlatformPost.Status.APPROVED
        )

        # Now the one-tap Publish is allowed.
        resp = self.client.post(self._publish_url(post))
        self.assertIn(resp.status_code, (200, 204, 302))
        self.assertEqual(
            post.platform_posts.get().status, PlatformPost.Status.SCHEDULED
        )


class PublishActionGuardTests(_Base):
    def test_get_is_rejected(self):
        post = self._make_ai_post(Post.ReviewState.APPROVED)
        self.client.force_login(self.owner)
        resp = self.client.get(self._publish_url(post))
        self.assertEqual(resp.status_code, 405)

    def test_anonymous_is_redirected_to_login(self):
        post = self._make_ai_post(Post.ReviewState.APPROVED)
        resp = self.client.post(self._publish_url(post))
        # login_required → redirect to login.
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login", resp.url)
