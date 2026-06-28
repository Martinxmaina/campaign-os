"""End-to-end tests for the /api/v1 reporting surface."""
from __future__ import annotations

import pytest
from django.test import Client
from django.utils import timezone

from apps.api_keys import services
from apps.members.models import PERMISSION_KEYS, OrgMembership, WorkspaceMembership


@pytest.fixture
def user(db):
    from apps.accounts.models import User

    return User.objects.create_user(
        email="reporting-owner@example.com",
        password="testpass123",
        name="Reporting Owner",
        tos_accepted_at=timezone.now(),
    )


@pytest.fixture
def organization(db):
    from apps.organizations.models import Organization

    return Organization.objects.create(name="Reporting Org")


@pytest.fixture
def workspace(db, organization):
    from apps.workspaces.models import Workspace

    return Workspace.objects.create(name="Reporting WS", organization=organization)


@pytest.fixture
def owner_memberships(db, user, organization, workspace):
    OrgMembership.objects.create(user=user, organization=organization, org_role=OrgMembership.OrgRole.OWNER)
    return WorkspaceMembership.objects.create(
        user=user, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
    )


@pytest.fixture
def linkedin_account(db, workspace):
    from apps.social_accounts.models import SocialAccount

    return SocialAccount.objects.create(
        workspace=workspace,
        platform="linkedin",
        account_platform_id="li-rep",
        account_name="LI Reporting",
        connection_status="connected",
    )


@pytest.fixture
def issued_key(db, user, owner_memberships, workspace, linkedin_account):
    return services.issue_api_key(
        workspace=workspace,
        social_accounts=[linkedin_account],
        issued_by=user,
        name="reporting-smoke",
        permissions=list(PERMISSION_KEYS),
    )


@pytest.fixture
def no_analytics_key(db, user, owner_memberships, workspace, linkedin_account):
    return services.issue_api_key(
        workspace=workspace,
        social_accounts=[linkedin_account],
        issued_by=user,
        name="reporting-no-analytics",
        permissions=[p for p in PERMISSION_KEYS if p != "view_analytics"],
    )


class _SecureClient(Client):
    def generic(self, method, path, *args, **kwargs):
        kwargs["secure"] = True
        return super().generic(method, path, *args, **kwargs)


@pytest.fixture
def client_with_token(issued_key):
    return _SecureClient(HTTP_AUTHORIZATION=f"Bearer {issued_key.plaintext_token}")


@pytest.fixture
def client_no_analytics(no_analytics_key):
    return _SecureClient(HTTP_AUTHORIZATION=f"Bearer {no_analytics_key.plaintext_token}")


def _make_post(workspace, account, *, status="draft", campaign="", scheduled_at=None, published_at=None):
    """Create a Post with one PlatformPost child in the given status."""
    from apps.composer.models import PlatformPost, Post

    post = Post.objects.create(
        workspace=workspace,
        title=f"Post {status}",
        caption="Body text for the post.",
        campaign=campaign,
        scheduled_at=scheduled_at,
        published_at=published_at,
    )
    PlatformPost.objects.create(
        post=post,
        social_account=account,
        status=status,
        scheduled_at=scheduled_at,
        published_at=published_at,
    )
    return post


@pytest.mark.django_db
class TestPipeline:
    def test_pipeline_matches_progress_helper(self, client_with_token, workspace, linkedin_account):
        from apps.content_intake.progress import content_pipeline_progress

        _make_post(workspace, linkedin_account, status="draft")
        _make_post(workspace, linkedin_account, status="published", published_at=timezone.now())

        r = client_with_token.get("/api/v1/pipeline")
        assert r.status_code == 200
        body = r.json()
        expected = content_pipeline_progress(workspace)
        assert body["total"] == expected["total"]
        assert body["published"] == expected["published"]
        assert [s["key"] for s in body["stages"]] == [s["key"] for s in expected["stages"]]

    def test_pipeline_requires_auth(self):
        r = _SecureClient().get("/api/v1/pipeline")
        assert r.status_code == 401


@pytest.mark.django_db
class TestContent:
    def test_lists_workspace_content_with_filters(self, client_with_token, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="published", campaign="EGM", published_at=timezone.now())
        _make_post(workspace, linkedin_account, status="draft", campaign="Other")

        r = client_with_token.get("/api/v1/content?campaign=EGM")
        assert r.status_code == 200
        body = r.json()
        assert body["has_more"] is False
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["campaign"] == "EGM"
        assert item["status"] == "published"
        assert item["platforms"][0]["platform"] == "linkedin"

    def test_pagination_cursor(self, client_with_token, workspace, linkedin_account):
        for _ in range(3):
            _make_post(workspace, linkedin_account, status="draft")
        r1 = client_with_token.get("/api/v1/content?limit=2")
        b1 = r1.json()
        assert len(b1["items"]) == 2 and b1["has_more"] is True and b1["next_cursor"]
        r2 = client_with_token.get(f"/api/v1/content?limit=2&cursor={b1['next_cursor']}")
        b2 = r2.json()
        assert len(b2["items"]) == 1 and b2["has_more"] is False

    def test_cross_workspace_isolation(self, client_with_token, organization):
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.models import Workspace

        other_ws = Workspace.objects.create(name="Other WS", organization=organization)
        other_acct = SocialAccount.objects.create(
            workspace=other_ws, platform="linkedin", account_platform_id="li-other",
            account_name="Other LI", connection_status="connected",
        )
        _make_post(other_ws, other_acct, status="published", published_at=timezone.now())

        r = client_with_token.get("/api/v1/content")
        assert r.status_code == 200
        assert r.json()["items"] == []


@pytest.mark.django_db
class TestCampaigns:
    def test_campaign_rollup(self, client_with_token, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="published", campaign="EGM", published_at=timezone.now())
        _make_post(workspace, linkedin_account, status="draft", campaign="EGM")

        r = client_with_token.get("/api/v1/campaigns")
        assert r.status_code == 200
        items = r.json()["items"]
        egm = next(c for c in items if c["name"] == "EGM")
        assert egm["content_count"] == 2
        assert egm["platforms"] == ["linkedin"]
        assert egm["analytics"]["available"] in (True, False)  # present (key has view_analytics)

    def test_campaign_analytics_omitted_without_permission(self, client_no_analytics, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="draft", campaign="EGM")
        r = client_no_analytics.get("/api/v1/campaigns")
        assert r.status_code == 200
        egm = next(c for c in r.json()["items"] if c["name"] == "EGM")
        assert egm["analytics"] is None


@pytest.mark.django_db
class TestOverview:
    def test_overview_composition(self, client_with_token, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="published", campaign="EGM", published_at=timezone.now())
        _make_post(
            workspace, linkedin_account, status="scheduled", campaign="EGM",
            scheduled_at=timezone.now() + timezone.timedelta(days=1),
        )

        r = client_with_token.get("/api/v1/overview")
        assert r.status_code == 200
        body = r.json()
        assert body["workspace_id"] == str(workspace.id)
        assert body["content"]["total"] == 2
        assert body["content"]["scheduled_next_7d"] == 1
        assert body["pipeline"]["total"] >= 2
        assert any(c["name"] == "EGM" for c in body["campaigns"])
        assert "available" in body["analytics"]

    def test_overview_analytics_unavailable_without_permission(self, client_no_analytics, workspace, linkedin_account):
        _make_post(workspace, linkedin_account, status="draft")
        r = client_no_analytics.get("/api/v1/overview")
        assert r.status_code == 200
        assert r.json()["analytics"]["available"] is False


@pytest.mark.django_db
class TestPlumbing:
    def test_writes_audit_row(self, client_with_token, workspace, linkedin_account):
        from apps.api_keys.models import ApiKeyAuditLog

        _make_post(workspace, linkedin_account, status="draft")
        client_with_token.get("/api/v1/overview")
        assert ApiKeyAuditLog.objects.filter(action="reporting.overview.read").exists()
