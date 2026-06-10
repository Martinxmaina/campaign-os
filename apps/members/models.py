import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.managers import OrgScopedManager


class OrgMembership(models.Model):
    class OrgRole(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="org_memberships",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    org_role = models.CharField(max_length=20, choices=OrgRole.choices, default=OrgRole.MEMBER)
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(blank=True, null=True)

    objects = OrgScopedManager()

    class Meta:
        db_table = "members_org_membership"
        unique_together = [("user", "organization")]

    def __str__(self):
        return f"{self.user.email} - {self.organization.name} ({self.org_role})"


class WorkspaceMembership(models.Model):
    class WorkspaceRole(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        CAMPAIGN_OWNER = "campaign_owner", "Campaign Owner"
        PRINCIPAL = "principal", "Principal"
        PILLAR_LEAD = "pillar_lead", "Pillar Lead"
        MANAGER = "manager", "Manager"
        EDITOR = "editor", "Editor"
        MEMBER = "member", "Member"
        CONTRIBUTOR = "contributor", "Contributor"
        CLIENT = "client", "Client"
        VIEWER = "viewer", "Viewer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    workspace_role = models.CharField(
        max_length=20,
        choices=WorkspaceRole.choices,
        default=WorkspaceRole.VIEWER,
    )
    pillar = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Pillar/theme scope for pillar_lead role (e.g. 'energy', 'agribusiness')",
    )
    house = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="House/workspace scope (e.g. 'WAIIS', 'AfCEN')",
    )
    custom_role = models.ForeignKey(
        "CustomRole",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="memberships",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "members_workspace_membership"
        unique_together = [("user", "workspace")]

    def __str__(self):
        role = self.custom_role.name if self.custom_role else self.workspace_role
        return f"{self.user.email} - {self.workspace.name} ({role})"

    def clean(self):
        """Enforce role-scoped constraints on pillar/house fields.

        ``pillar`` must only be set when the role is ``pillar_lead``.
        ``house`` is unrestricted across roles (it denotes the workspace brand
        context, e.g. 'WAIIS', 'AfCEN', and is valid for any role), but stale
        ``pillar`` data left behind after a role change from ``pillar_lead`` to
        anything else is silently misleading — raise ValidationError so the
        caller knows to clear it.
        """
        from django.core.exceptions import ValidationError

        if self.workspace_role != self.WorkspaceRole.PILLAR_LEAD and self.pillar:
            raise ValidationError(
                {
                    "pillar": (
                        "The 'pillar' field may only be set when workspace_role is "
                        f"'pillar_lead'. Current role is '{self.workspace_role}'. "
                        "Clear the pillar field before changing the role."
                    )
                }
            )

    def save(self, *args, **kwargs):
        """Ensure clean() runs on every programmatic save, not just form saves.

        We call validate_constraints=False to avoid re-running the DB-level
        unique_together check on partial updates (update_fields), which would
        raise a spurious IntegrityError on rows that already own their slot.
        The clean() method itself carries the constraint we actually care about
        (pillar/role consistency).
        """
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    @property
    def effective_permissions(self):
        """Return the effective permission dict for this membership."""
        if self.custom_role:
            return self.custom_role.permissions
        return BUILTIN_ROLE_PERMISSIONS.get(self.workspace_role, {})


class CustomRole(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="custom_roles",
    )
    name = models.CharField(max_length=100)
    permissions = models.JSONField(
        default=dict,
        help_text="Permission keys mapped to booleans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrgScopedManager()

    class Meta:
        db_table = "members_custom_role"
        unique_together = [("organization", "name")]

    def __str__(self):
        return f"{self.name} ({self.organization.name})"


def _generate_invitation_token():
    return secrets.token_urlsafe(32)


class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField()
    org_role = models.CharField(
        max_length=20,
        choices=OrgMembership.OrgRole.choices,
        default=OrgMembership.OrgRole.MEMBER,
    )
    workspace_assignments = models.JSONField(
        default=list,
        help_text='List of {"workspace_id": "...", "role": "..."}',
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_invitations",
    )
    token = models.CharField(max_length=255, unique=True, default=_generate_invitation_token)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgScopedManager()

    class Meta:
        db_table = "members_invitation"

    def __str__(self):
        return f"Invitation to {self.email} for {self.organization.name}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_accepted(self):
        return self.accepted_at is not None


# Built-in workspace role permission mappings
PERMISSION_KEYS = [
    "create_posts",
    "edit_others_posts",
    "approve_posts",
    "publish_directly",
    "manage_social_accounts",
    "view_analytics",
    "use_inbox",
    "reply_from_inbox",
    "manage_workspace_settings",
    "upload_media",
    "edit_media",
    "delete_media",
    "manage_media",
]

BUILTIN_ROLE_PERMISSIONS = {
    "owner": {k: True for k in PERMISSION_KEYS},
    # admin mirrors owner: a workspace admin has full authority over the
    # workspace (manage settings, approve, publish, etc.). If future requirements
    # need to restrict specific permissions for admin vs owner, update this entry
    # and add a test asserting the divergence.
    "admin": {k: True for k in PERMISSION_KEYS},
    # campaign_owner intentionally mirrors owner: within their campaign scope
    # they need full authority to approve, publish, and manage accounts.
    # This is deliberate RBAC design — campaign owners are scoped to a single
    # workspace/campaign, so they hold all permissions within that scope just
    # as a workspace owner does. If future requirements restrict certain
    # permissions for campaign_owner, update this entry and add a test to
    # assert the divergence. See Task 3 (RBAC — campaign_owner/principal/
    # pillar_lead roles) and the associated test_campaign_owner_vs_owner test.
    "campaign_owner": {k: True for k in PERMISSION_KEYS},
    "principal": {
        "create_posts": True,
        "edit_others_posts": True,
        "approve_posts": True,
        "publish_directly": True,
        "manage_social_accounts": False,
        "view_analytics": True,
        "use_inbox": True,
        "reply_from_inbox": True,
        "manage_workspace_settings": False,
        "upload_media": True,
        "edit_media": True,
        "delete_media": False,
        "manage_media": False,
    },
    "pillar_lead": {
        "create_posts": True,
        "edit_others_posts": True,
        "approve_posts": True,
        "publish_directly": False,
        "manage_social_accounts": False,
        "view_analytics": True,
        "use_inbox": False,
        "reply_from_inbox": False,
        "manage_workspace_settings": False,
        "upload_media": True,
        "edit_media": True,
        "delete_media": False,
        "manage_media": False,
    },
    "member": {
        "create_posts": True,
        "edit_others_posts": False,
        "approve_posts": False,
        "publish_directly": False,
        "manage_social_accounts": False,
        "view_analytics": False,
        "use_inbox": False,
        "reply_from_inbox": False,
        "manage_workspace_settings": False,
        "upload_media": True,
        "edit_media": True,
        "delete_media": False,
        "manage_media": False,
    },
    "manager": {
        "create_posts": True,
        "edit_others_posts": True,
        "approve_posts": True,
        "publish_directly": True,
        "manage_social_accounts": True,
        "view_analytics": True,
        "use_inbox": True,
        "reply_from_inbox": True,
        "manage_workspace_settings": False,
        "upload_media": True,
        "edit_media": True,
        "delete_media": True,
        "manage_media": True,
    },
    "editor": {
        "create_posts": True,
        "edit_others_posts": True,
        "approve_posts": False,
        "publish_directly": False,
        "manage_social_accounts": False,
        "view_analytics": True,
        "use_inbox": True,
        "reply_from_inbox": True,
        "manage_workspace_settings": False,
        "upload_media": True,
        "edit_media": True,
        "delete_media": True,
        "manage_media": False,
    },
    "contributor": {
        "create_posts": True,
        "edit_others_posts": False,
        "approve_posts": False,
        "publish_directly": False,
        "manage_social_accounts": False,
        "view_analytics": False,
        "use_inbox": False,
        "reply_from_inbox": False,
        "manage_workspace_settings": False,
        "upload_media": True,
        "edit_media": True,
        "delete_media": False,
        "manage_media": False,
    },
    "client": {
        "create_posts": False,
        "edit_others_posts": False,
        "approve_posts": True,
        "publish_directly": False,
        "manage_social_accounts": False,
        "view_analytics": True,
        "use_inbox": False,
        "reply_from_inbox": False,
        "manage_workspace_settings": False,
        "upload_media": False,
        "edit_media": False,
        "delete_media": False,
        "manage_media": False,
    },
    "viewer": {
        "create_posts": False,
        "edit_others_posts": False,
        "approve_posts": False,
        "publish_directly": False,
        "manage_social_accounts": False,
        "view_analytics": True,
        "use_inbox": False,
        "reply_from_inbox": False,
        "manage_workspace_settings": False,
        "upload_media": False,
        "edit_media": False,
        "delete_media": False,
        "manage_media": False,
    },
}


# ---------------------------------------------------------------------------
# Org-level permission model
# ---------------------------------------------------------------------------
# The workspace permission system above is workspace-scoped via
# ``WorkspaceMembership.effective_permissions``. The Intelligence integration
# needs ORG-scoped permission checks (subscriptions and Stripe billing are
# tied to the Organization, not any one workspace). Rather than expand the
# workspace system to do double duty, we introduce a parallel, narrower
# org-permission table keyed on ``OrgMembership.org_role``.
#
# Add new keys here as future features need org-scoped gating.

ORG_PERMISSION_KEYS = (
    ("manage_intelligence_billing", "Manage Intelligence subscription + billing"),
    ("use_intelligence", "Use Intelligence tools"),
    ("manage_api_keys", "Issue and revoke Agent API keys for any workspace in the org"),
)


BUILTIN_ORG_PERMISSIONS = {
    OrgMembership.OrgRole.OWNER: {
        "manage_intelligence_billing",
        "use_intelligence",
        "manage_api_keys",
    },
    OrgMembership.OrgRole.ADMIN: {
        "manage_intelligence_billing",
        "use_intelligence",
        "manage_api_keys",
    },
    OrgMembership.OrgRole.MEMBER: {
        "use_intelligence",
    },
}


def has_org_permission(membership, key):
    """Return True if ``membership`` grants the given org-permission key.

    ``membership`` is an ``OrgMembership`` or None (e.g., the user has no
    membership in the org being checked). None always returns False.
    """
    if membership is None:
        return False
    return key in BUILTIN_ORG_PERMISSIONS.get(membership.org_role, set())
