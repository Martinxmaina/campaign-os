import pytest
from apps.members.models import WorkspaceMembership, BUILTIN_ROLE_PERMISSIONS

def test_campaign_owner_can_approve():
    perms = BUILTIN_ROLE_PERMISSIONS["campaign_owner"]
    assert perms["approve_posts"] is True
    assert perms["create_posts"] is True

def test_principal_can_approve():
    perms = BUILTIN_ROLE_PERMISSIONS["principal"]
    assert perms["approve_posts"] is True

def test_pillar_lead_cannot_publish_directly():
    perms = BUILTIN_ROLE_PERMISSIONS["pillar_lead"]
    assert perms["publish_directly"] is False
    assert perms["create_posts"] is True
    assert perms["approve_posts"] is True

def test_member_cannot_approve():
    perms = BUILTIN_ROLE_PERMISSIONS["member"]
    assert perms["approve_posts"] is False
    assert perms["create_posts"] is True

def test_campaign_os_roles_in_choices():
    choices = dict(WorkspaceMembership.WorkspaceRole.choices)
    assert "campaign_owner" in choices
    assert "principal" in choices
    assert "pillar_lead" in choices
    assert "member" in choices
