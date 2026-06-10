import pytest
from apps.social_accounts.models import SocialAccount


@pytest.fixture
def make_social_account(db):
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="Health Org")
    workspace = Workspace.objects.create(name="Health WS", organization=org)
    counter = {"n": 0}

    def _make():
        counter["n"] += 1
        return SocialAccount.objects.create(
            workspace=workspace,
            platform="facebook",
            account_platform_id=f"acct-{counter['n']}",
            account_name=f"Acct {counter['n']}",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )

    return _make


@pytest.mark.django_db
def test_schedule_all_fans_out_one_per_account(monkeypatch, make_social_account):
    from apps.social_accounts import tasks

    a1 = make_social_account()
    a2 = make_social_account()
    called = []
    monkeypatch.setattr(
        tasks.check_social_account_health, "delay", lambda account_id: called.append(account_id)
    )
    tasks.schedule_all_health_checks()
    assert set(called) == {str(a1.id), str(a2.id)}
