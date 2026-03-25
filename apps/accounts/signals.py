from allauth.account.signals import user_signed_up
from django.dispatch import receiver


@receiver(user_signed_up)
def create_organization_on_signup(sender, request, user, **kwargs):
    """Auto-create an Organization when a new user signs up."""
    from apps.members.models import OrgMembership
    from apps.organizations.models import Organization

    # Check if user was invited to an existing org
    if OrgMembership.objects.filter(user=user).exists():
        return

    # Detect timezone from request if available
    timezone = "UTC"

    org = Organization.objects.create(
        name=f"{user.display_name}'s Organization",
        default_timezone=timezone,
    )

    OrgMembership.objects.create(
        user=user,
        organization=org,
        org_role=OrgMembership.OrgRole.OWNER,
    )
