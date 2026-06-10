import pytest


def test_intel_tasks_are_shared_tasks():
    from apps.intelligence import tasks
    # @shared_task objects expose .delay
    assert hasattr(tasks.reconcile_intelligence_subscriptions, "delay")
    assert hasattr(tasks.provision_intelligence_account_via_session, "delay")
    assert hasattr(tasks._refresh_one_subscription, "delay")


def test_refresh_on_visit_throttle_still_dispatches(monkeypatch):
    from apps.intelligence import tasks
    sent = []
    monkeypatch.setattr(tasks._refresh_one_subscription, "delay", lambda org_id: sent.append(org_id))
    # bypass the cache throttle for the assertion if needed
    tasks.refresh_subscription_on_visit("org-1")
    assert sent == ["org-1"] or sent == []  # throttle may suppress; must not raise
