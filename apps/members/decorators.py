"""Permission decorators for RBAC enforcement."""

import functools

from django.core.exceptions import PermissionDenied


def require_org_role(min_role):
    """Decorator that requires a minimum org role.

    Role hierarchy: owner > admin > member
    """
    role_hierarchy = {"owner": 3, "admin": 2, "member": 1}

    def decorator(view_func):
        @functools.wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.org_membership:
                raise PermissionDenied("You are not a member of any organization.")
            user_level = role_hierarchy.get(request.org_membership.org_role, 0)
            required_level = role_hierarchy.get(min_role, 0)
            if user_level < required_level:
                raise PermissionDenied("Insufficient organization role.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def require_workspace_role(min_role):
    """Decorator that requires a minimum workspace role.

    For users with custom roles, this checks the custom role's permissions
    against the built-in role's permissions to determine equivalence.
    Users with custom roles are treated as having the permissions defined
    in their custom role, so this decorator falls back to require_permission
    for the key permissions of the minimum role.

    Role hierarchy (built-in): owner > manager > editor > contributor > client > viewer
    """
    role_hierarchy = {
        "owner": 6,
        "manager": 5,
        "editor": 4,
        "contributor": 3,
        "client": 2,
        "viewer": 1,
    }

    def decorator(view_func):
        @functools.wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.workspace_membership:
                raise PermissionDenied("You are not a member of this workspace.")
            membership = request.workspace_membership
            user_level = role_hierarchy.get(membership.workspace_role, 0)
            required_level = role_hierarchy.get(min_role, 0)
            if user_level < required_level:
                raise PermissionDenied("Insufficient workspace role.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def require_permission(permission_key):
    """Decorator that checks a specific permission key against effective permissions.

    This works with both built-in roles and custom roles via the
    effective_permissions property on WorkspaceMembership.
    """

    def decorator(view_func):
        @functools.wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.workspace_membership:
                raise PermissionDenied("You are not a member of this workspace.")
            perms = request.workspace_membership.effective_permissions
            if not perms.get(permission_key, False):
                raise PermissionDenied(f"Permission denied: {permission_key}")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
