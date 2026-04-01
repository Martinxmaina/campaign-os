from allauth.account.signals import user_signed_up
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


def provision_organization_and_workspace(user):
    """Create a default Organization, Workspace, and memberships for a new user.

    Skips if the user already belongs to an organization (e.g. invited users).
    Safe to call multiple times — the guard is idempotent.
    """
    from apps.members.models import Invitation, OrgMembership, WorkspaceMembership
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace

    # Skip if user was invited to an existing org or already provisioned
    if OrgMembership.objects.filter(user=user).exists():
        return

    # Skip if there's a pending invitation for this email — the user_signed_up
    # signal will handle invite acceptance. This prevents post_save (which fires
    # before user_signed_up) from creating a default org for invited users.
    if Invitation.objects.filter(
        email__iexact=user.email,
        accepted_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).exists():
        return

    org = Organization.objects.create(
        name="My Organization",
        default_timezone="UTC",
    )

    OrgMembership.objects.create(
        user=user,
        organization=org,
        org_role=OrgMembership.OrgRole.OWNER,
    )

    # Create a default workspace so the user can start immediately
    workspace = Workspace.objects.create(
        organization=org,
        name="My Workspace",
        description="Your default workspace. Rename it anytime.",
    )

    WorkspaceMembership.objects.create(
        user=user,
        workspace=workspace,
        workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
    )

    # Set as last workspace so dashboard redirects here
    user.last_workspace_id = workspace.id
    user.save(update_fields=["last_workspace_id"])


@receiver(user_signed_up)
def create_organization_on_signup(sender, request, user, **kwargs):
    """Handle allauth signup — create org + workspace.

    If the user signed up via an invitation link, accept the invitation
    instead of creating a default org. The invite token is stored in
    the session by the accept_invite view.
    """
    pending_token = request.session.pop("pending_invite_token", None)
    if pending_token:
        from apps.members.models import Invitation
        from apps.members.services import accept_invitation

        try:
            invitation = Invitation.objects.get(
                token=pending_token,
                accepted_at__isnull=True,
            )
            if not invitation.is_expired:
                accept_invitation(invitation, user)
                return  # Skip default provisioning
        except Invitation.DoesNotExist:
            pass  # Fall through to default provisioning

    provision_organization_and_workspace(user)


@receiver(post_save, sender="accounts.User")
def create_organization_on_user_create(sender, instance, created, **kwargs):
    """Handle any user creation path (createsuperuser, admin, shell).

    The allauth signal fires *after* post_save, so for normal signups
    post_save runs first and the allauth handler is a no-op (idempotent guard).
    """
    if created:
        provision_organization_and_workspace(instance)
