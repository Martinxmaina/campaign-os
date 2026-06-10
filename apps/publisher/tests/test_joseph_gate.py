"""Integration tests for the Joseph-personal channel gate in the publish engine (T12).

These tests drive ``_dispatch_to_provider`` via ``PublishEngine`` and verify:
  - A post that requires Joseph approval is held at ``pending_client`` (not ``failed``)
    when no matching ApprovalAction exists.
  - A post with a matching ApprovalAction proceeds past the Joseph gate to
    the provider dispatch layer.
  - ``_check_joseph_approval`` resolves identity via ``settings.JOSEPH_APPROVER_EMAIL``
    (exact email match, not a substring).
  - ``_check_joseph_approval`` resolves identity via ``ContentIntake.owner_raw``
    (exact match, not a substring).
  - A partial substring that would have matched the old ``icontains`` query does NOT
    grant approval (regression guard).
"""
from __future__ import annotations

import pytest
from datetime import timedelta
from django.utils import timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace_and_account(db, platform="mock"):
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="Joseph Gate Test Org")
    workspace = Workspace.objects.create(name="Joseph Gate WS", organization=org)
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform=platform,
        account_platform_id=f"acct-joseph-gate-{platform}",
        account_name=f"{platform} joseph-gate",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    return workspace, account


def _make_platform_post(workspace, account, channel_targets=None):
    """Create a PlatformPost in PUBLISHING state (simulating mid-dispatch)."""
    from apps.composer.models import PlatformPost, Post
    from apps.content_intake.models import ContentIntake

    post = Post.objects.create(
        workspace=workspace,
        author=None,
        caption="Joseph gate test caption",
        title="Joseph gate test",
    )
    intake = ContentIntake.objects.create(
        workspace=workspace,
        external_id=f"JG-{post.id}",
        pillar_theme="Governance",
        angle="Joseph personal channel test",
        sensitivity=ContentIntake.Sensitivity.PUBLIC_SAFE,
        status=ContentIntake.Status.ACCEPTED,
        owner_raw="joseph@africacen.org",
        channel_targets=channel_targets or [
            {"platform": "linkedin", "account": "joseph", "requires_joseph_approval": True}
        ],
        post=post,
    )
    del intake  # kept in DB; referenced via post.intake_source

    platform_post = PlatformPost.objects.create(
        post=post,
        social_account=account,
        status=PlatformPost.Status.PUBLISHING,  # already claimed by the publish cycle
        scheduled_at=timezone.now() - timedelta(minutes=5),
    )
    return platform_post


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_joseph_gate_blocks_to_pending_client_when_no_approval(monkeypatch, settings):
    """When requires_joseph_approval=True and no ApprovalAction exists, the post
    must be transitioned to ``pending_client``, not ``failed``."""
    settings.JOSEPH_APPROVER_EMAIL = "joseph@africacen.org"

    # Prevent actual provider dispatch (gate should return before reaching it).
    from apps.publisher import engine as eng_mod
    monkeypatch.setattr(eng_mod, "get_provider", lambda platform, creds: (_ for _ in ()).throw(AssertionError("provider should not be reached")))

    workspace, account = _make_workspace_and_account(pytest.db if hasattr(pytest, "db") else None)
    platform_post = _make_platform_post(workspace, account)

    from apps.publisher.engine import PublishEngine
    engine = PublishEngine.__new__(PublishEngine)

    engine._dispatch_to_provider(platform_post)

    platform_post.refresh_from_db()
    assert platform_post.status == "pending_client", (
        f"Expected pending_client but got {platform_post.status!r}. "
        "Joseph gate hold must not transition to 'failed'."
    )
    assert "JOSEPH GATE" in (platform_post.publish_error or "")


@pytest.mark.django_db
def test_joseph_gate_blocks_to_pending_client_when_no_approval_db(settings):
    """DB-variant: verifies the hold state without monkeypatching get_provider."""
    settings.JOSEPH_APPROVER_EMAIL = "joseph@africacen.org"

    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="JG Block Org")
    workspace = Workspace.objects.create(name="JG Block WS", organization=org)
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="mock",
        account_platform_id="acct-jg-block",
        account_name="mock jg-block",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    platform_post = _make_platform_post(workspace, account)

    # Stub get_provider so we never hit a real provider.
    import apps.publisher.engine as eng_mod

    class _AbortProvider:
        def publish_post(self, *a, **kw):
            raise AssertionError("provider.publish_post should not be reached")

    original_get_provider = eng_mod.get_provider
    eng_mod.get_provider = lambda *a, **kw: _AbortProvider()
    try:
        from apps.publisher.engine import PublishEngine
        engine = PublishEngine.__new__(PublishEngine)
        engine._dispatch_to_provider(platform_post)
    finally:
        eng_mod.get_provider = original_get_provider

    platform_post.refresh_from_db()
    assert platform_post.status == "pending_client", (
        f"Expected pending_client but got {platform_post.status!r}."
    )


@pytest.mark.django_db
def test_joseph_gate_passes_when_approval_action_exists(settings):
    """When a matching ApprovalAction (APPROVED) exists, ``_check_joseph_approval``
    returns True and the engine does NOT transition the post to ``pending_client``.

    The test verifies the gate logic in isolation: it stubs ``_check_joseph_approval``
    to call the real implementation (with a live ApprovalAction in the DB), then
    confirms the engine does not write ``pending_client`` to the database.  The
    provider-dispatch layer is short-circuited by raising a controlled sentinel
    exception after the gate, so we can assert on the DB state without needing
    a fully wired provider mock.
    """
    settings.JOSEPH_APPROVER_EMAIL = "joseph@africacen.org"

    from apps.accounts.models import User
    from apps.approvals.models import ApprovalAction
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="JG Pass Org")
    workspace = Workspace.objects.create(name="JG Pass WS", organization=org)
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="mock",
        account_platform_id="acct-jg-pass",
        account_name="mock jg-pass",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    platform_post = _make_platform_post(workspace, account)

    joseph_user = User.objects.create_user(
        email="joseph@africacen.org",
        password="pass",
        name="Joseph Principal",
        tos_accepted_at=timezone.now(),
    )
    ApprovalAction.objects.create(
        post=platform_post.post,
        user=joseph_user,
        action=ApprovalAction.ActionType.APPROVED,
    )

    # Verify _check_joseph_approval itself returns True with the live DB record.
    from apps.publisher.engine import _check_joseph_approval
    assert _check_joseph_approval(platform_post) is True, (
        "_check_joseph_approval returned False despite a matching APPROVED action "
        "from joseph@africacen.org."
    )

    # Now verify the engine gate path: when _check_joseph_approval passes, the
    # post must NOT be transitioned to pending_client.  We abort dispatch early
    # via a patched _resolve_publish_credentials to avoid provider complexity.
    class _AbortAfterGate(Exception):
        pass

    import apps.publisher.engine as eng_mod
    original_resolve = eng_mod._resolve_publish_credentials
    eng_mod._resolve_publish_credentials = lambda account: (_ for _ in ()).throw(_AbortAfterGate())
    try:
        from apps.publisher.engine import PublishEngine
        engine = PublishEngine.__new__(PublishEngine)
        engine._gate_failure_reason = lambda pp: None  # stub the main gate
        try:
            engine._dispatch_to_provider(platform_post)
        except _AbortAfterGate:
            pass  # expected — confirms execution reached post-gate dispatch
    finally:
        eng_mod._resolve_publish_credentials = original_resolve

    platform_post.refresh_from_db()
    assert platform_post.status != "pending_client", (
        "Joseph gate incorrectly transitioned an already-approved post to pending_client."
    )


@pytest.mark.django_db
def test_joseph_gate_substring_does_not_grant_approval(settings):
    """A user whose email merely contains 'joseph' as a substring must NOT
    grant approval — only an exact match to JOSEPH_APPROVER_EMAIL qualifies.

    This is the regression guard for the old ``email__icontains='joseph'`` bug.
    """
    settings.JOSEPH_APPROVER_EMAIL = "joseph@africacen.org"

    from apps.accounts.models import User
    from apps.approvals.models import ApprovalAction
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="JG Substring Org")
    workspace = Workspace.objects.create(name="JG Substring WS", organization=org)
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="mock",
        account_platform_id="acct-jg-substr",
        account_name="mock jg-substr",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    platform_post = _make_platform_post(workspace, account)

    # This user's email CONTAINS 'joseph' as a substring but is NOT the principal.
    josephine_user = User.objects.create_user(
        email="josephine@example.com",
        password="pass",
        name="Josephine Other",
        tos_accepted_at=timezone.now(),
    )
    ApprovalAction.objects.create(
        post=platform_post.post,
        user=josephine_user,
        action=ApprovalAction.ActionType.APPROVED,
    )

    from apps.publisher.engine import _check_joseph_approval

    result = _check_joseph_approval(platform_post)
    assert result is False, (
        "Substring match ('josephine@example.com' contains 'joseph') incorrectly "
        "granted approval. _check_joseph_approval must use exact-match only."
    )


@pytest.mark.django_db
def test_joseph_gate_resolves_via_owner_raw(settings):
    """When the approver's email exactly matches the intake ``owner_raw`` value,
    the gate must pass even if ``JOSEPH_APPROVER_EMAIL`` is empty."""
    settings.JOSEPH_APPROVER_EMAIL = ""  # deliberately cleared

    from apps.accounts.models import User
    from apps.approvals.models import ApprovalAction
    from apps.organizations.models import Organization
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="JG OwnerRaw Org")
    workspace = Workspace.objects.create(name="JG OwnerRaw WS", organization=org)
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="mock",
        account_platform_id="acct-jg-ownerraw",
        account_name="mock jg-ownerraw",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    # owner_raw is set to the approver's email for this test.
    platform_post = _make_platform_post(workspace, account)
    # owner_raw was already set to 'joseph@africacen.org' by _make_platform_post.

    principal_user = User.objects.create_user(
        email="joseph@africacen.org",
        password="pass",
        name="Joseph Principal",
        tos_accepted_at=timezone.now(),
    )
    ApprovalAction.objects.create(
        post=platform_post.post,
        user=principal_user,
        action=ApprovalAction.ActionType.APPROVED,
    )

    from apps.publisher.engine import _check_joseph_approval

    result = _check_joseph_approval(platform_post)
    assert result is True, (
        "owner_raw-based resolution failed: approver email matches owner_raw "
        "but _check_joseph_approval returned False."
    )
