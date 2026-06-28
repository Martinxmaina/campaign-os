"""C2 density render-smoke for the Content Studio board.

``console:content`` is a GLOBAL ``/console/content`` route (no ``workspace_id``
kwarg). The studio view resolves the active workspace from the user via
``request.workspace`` (RBACMiddleware reads ``user.last_workspace_id``), so the
test sets ``last_workspace_id`` before the GET.

This guards the Phase C density refactor of ``console/content_studio.html`` +
``console/_studio_card.html``: the board must still render 200, the per-state
inline action FORMS must still be present (Submit for review / Approve /
Request changes / Reject / Publish), and the Edit link must remain.
"""
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def _member(workspace, org):
    user = User.objects.create_user(
        email="c2studio@example.com", password="pw", tos_accepted_at=timezone.now()
    )
    OrgMembership.objects.create(
        user=user, organization=org, org_role=OrgMembership.OrgRole.OWNER
    )
    WorkspaceMembership.objects.create(
        user=user, workspace=workspace,
        workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
    )
    user.last_workspace_id = workspace.id
    user.save(update_fields=["last_workspace_id"])
    return user


def test_studio_board_renders_200(client):
    org = Organization.objects.create(name="C2 Studio")
    workspace = Workspace.objects.create(organization=org, name="WAIIS")
    user = _member(workspace, org)
    client.force_login(user)

    resp = client.get(reverse("console:content"))
    assert resp.status_code == 200
    assert b"Content Studio" in resp.content


def test_studio_card_inline_actions_preserved(client):
    """The decluttering must keep every per-state action FORM + the Edit link."""
    org = Organization.objects.create(name="C2 Studio Actions")
    workspace = Workspace.objects.create(organization=org, name="WAIIS")
    user = _member(workspace, org)
    account = SocialAccount.objects.create(
        workspace=workspace, platform="mock", account_platform_id="mock-1",
        account_name="Mock", connection_status="connected",
    )
    # A draft post -> "Submit for review" form.
    draft = Post.objects.create(
        workspace=workspace, title="Draft one", caption="hello",
        review_state=Post.ReviewState.NONE,
    )
    PlatformPost.objects.create(
        post=draft, social_account=account, status=PlatformPost.Status.DRAFT,
    )
    # A pending_review post -> Approve / Request changes / Reject forms.
    pending = Post.objects.create(
        workspace=workspace, title="Pending one", caption="review me",
        review_state=Post.ReviewState.PENDING,
    )
    PlatformPost.objects.create(
        post=pending, social_account=account,
        status=PlatformPost.Status.PENDING_REVIEW,
    )
    client.force_login(user)

    resp = client.get(reverse("console:content"))
    assert resp.status_code == 200
    body = resp.content.decode()

    # Inline action endpoints (forms) survive the refactor.
    assert reverse("console:studio-submit-review", args=[draft.id]) in body
    assert reverse("console:approval-decide", args=[pending.id]) in body
    # The three decisions are still posted as hidden inputs.
    assert 'value="approve"' in body
    assert 'value="changes"' in body
    assert 'value="reject"' in body
    # Edit link to the composer is preserved on every card.
    assert reverse(
        "composer:compose_edit",
        kwargs={"workspace_id": draft.workspace_id, "post_id": draft.id},
    ) in body
    # No inline event handlers were introduced (CSP-safe).
    assert "onclick=" not in body
    assert "onsubmit=" not in body


def test_studio_card_shows_channels(client):
    """Each card lists its target channels (account name + platform) with a logo slot."""
    org = Organization.objects.create(name="Studio Channels")
    workspace = Workspace.objects.create(organization=org, name="WAIIS")
    user = _member(workspace, org)
    account = SocialAccount.objects.create(
        workspace=workspace, platform="blotato_linkedin", account_platform_id="ch-1",
        account_name="AfCEN", connection_status="connected",
    )
    post = Post.objects.create(workspace=workspace, title="Channel post", caption="hi")
    PlatformPost.objects.create(post=post, social_account=account, status=PlatformPost.Status.DRAFT)
    client.force_login(user)

    body = client.get(reverse("console:content")).content.decode()
    assert "AfCEN" in body  # the channel's name/logo chip renders on the card
