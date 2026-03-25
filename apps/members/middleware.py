"""RBAC middleware that resolves org role + workspace role on every request."""

from .models import OrgMembership, WorkspaceMembership


class RBACMiddleware:
    """Attach org and workspace context to the request.

    Sets:
        request.org - the user's Organization (or None)
        request.org_membership - the user's OrgMembership (or None)
        request.workspace - the current Workspace (or None, set by views)
        request.workspace_membership - the WorkspaceMembership (or None)

    Note: v1 supports one org per user. The query uses .first() which is
    correct since unique_together=("user", "organization") and v1 only
    creates one org membership per user. If multi-org is added later,
    this must resolve org from URL or session context.

    Resolution happens in process_view (not __call__) because
    request.resolver_match is only available after URL resolution,
    which occurs inside get_response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Initialize attributes; actual resolution happens in process_view
        request.org = None
        request.org_membership = None
        request.workspace = None
        request.workspace_membership = None

        # Resolve org membership early (doesn't need resolver_match)
        if hasattr(request, "user") and request.user.is_authenticated:
            # Resolve org membership.
            # In v1, each user belongs to exactly one organization.
            # If a workspace_id is in the URL, resolve org through the workspace
            # to ensure consistency.
            workspace_id = request.resolver_match.kwargs.get("workspace_id") if request.resolver_match else None

            if workspace_id:
                # Resolve workspace membership first, then derive org from it
                ws_membership = (
                    WorkspaceMembership.objects.filter(
                        user=request.user,
                        workspace_id=workspace_id,
                    )
                    .select_related("workspace__organization", "custom_role")
                    .first()
                )
                if ws_membership:
                    request.workspace = ws_membership.workspace
                    request.workspace_membership = ws_membership
                    # Resolve org from the workspace's organization
                    org = ws_membership.workspace.organization
                    org_membership = (
                        OrgMembership.objects.filter(
                            user=request.user,
                            organization=org,
                        )
                        .select_related("organization")
                        .first()
                    )
                    if org_membership:
                        request.org = org_membership.organization
                        request.org_membership = org_membership

            # If no workspace in URL (or workspace resolution failed), resolve org directly
            if request.org is None:
                org_membership = OrgMembership.objects.filter(user=request.user).select_related("organization").first()
                if org_membership:
                    request.org = org_membership.organization
                    request.org_membership = org_membership

        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Resolve workspace context from URL kwargs.

        This runs after URL resolution, so resolver_match and view_kwargs
        are available.
        """
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return None

        workspace_id = view_kwargs.get("workspace_id")
        if not workspace_id:
            return None

        ws_membership = (
            WorkspaceMembership.objects.filter(
                user=request.user,
                workspace_id=workspace_id,
            )
            .select_related("workspace__organization", "custom_role")
            .first()
        )
        if ws_membership:
            request.workspace = ws_membership.workspace
            request.workspace_membership = ws_membership
            # Also resolve org from workspace for consistency
            org = ws_membership.workspace.organization
            org_membership = (
                OrgMembership.objects.filter(
                    user=request.user,
                    organization=org,
                )
                .select_related("organization")
                .first()
            )
            if org_membership:
                request.org = org_membership.organization
                request.org_membership = org_membership

        return None
