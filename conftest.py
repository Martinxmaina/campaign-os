import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership
from apps.organizations.models import Organization


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Close DB connections leaked by eager Celery tasks after each test.

    With ``CELERY_TASK_ALWAYS_EAGER=True`` (test settings), Celery's Django
    fixup intentionally skips its ``task_prerun``/``task_postrun`` connection
    -closing hooks for eager tasks (see celery/fixups/django.py:
    ``if not is_eager``). So any DB connection opened while a task runs inline
    is never closed; it stays attached to the test database and blocks pytest
    -django from dropping/recreating it between tests and runs ("database is
    being accessed by other users" / "already exists"), which made the full
    suite flaky on this branch.

    We yield first so pytest-django's own fixture finalizers (the per-test
    transaction rollback) run, then close connections — but only when we are
    NOT inside a Django TestCase class, whose setUpClass wraps the entire
    class in a long-lived transaction that must outlive individual test
    teardowns. Closing connections mid-class would orphan that transaction.
    Production behaviour is untouched; this is a test-harness-only safeguard.
    """
    yield
    # Skip connection closing when the test belongs to a Django TestCase class
    # (identified by having _pre_setup / _post_teardown Django test methods),
    # since those classes hold a class-level wrapping transaction across all
    # tests in the class.
    import django.test

    if isinstance(getattr(item, "cls", None), type) and issubclass(
        item.cls, django.test.TransactionTestCase
    ):
        return
    from django.db import connections

    connections.close_all()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="test@example.com", password="testpass123", name="Test User", tos_accepted_at=timezone.now()
    )


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Test Organization")


@pytest.fixture
def org_owner(db, user, organization):
    OrgMembership.objects.create(user=user, organization=organization, org_role=OrgMembership.OrgRole.OWNER)
    return user


@pytest.fixture
def due_platform_post_factory(db, organization):
    """Build a due PlatformPost (status=scheduled, scheduled_at in the past).

    Creates the Workspace + SocialAccount + Post + PlatformPost chain so the
    publish engine's poll loop picks it up immediately. Accepts ``gate_id``,
    ``content_hash`` and ``platform`` to exercise the gate hook.
    """
    from datetime import timedelta

    from apps.composer.models import PlatformPost, Post
    from apps.social_accounts.models import SocialAccount
    from apps.workspaces.models import Workspace

    def _make(*, gate_id=None, content_hash="", platform="mock", caption="real text"):
        workspace = Workspace.objects.create(name="GateHook WS", organization=organization)
        account = SocialAccount.objects.create(
            workspace=workspace,
            platform=platform,
            account_platform_id=f"acct-{platform}",
            account_name=f"{platform} acct",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        post = Post.objects.create(workspace=workspace, author=None, caption=caption, title="t")
        return PlatformPost.objects.create(
            post=post,
            social_account=account,
            status=PlatformPost.Status.SCHEDULED,
            scheduled_at=timezone.now() - timedelta(minutes=5),
            gate_id=gate_id,
            content_hash=content_hash,
        )

    return _make
