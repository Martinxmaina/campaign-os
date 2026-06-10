"""Cross-cutting decorators for workspace scope enforcement."""

import functools

from django.core.exceptions import PermissionDenied


def workspace_required(view_func):
    """Require that ``request.workspace`` is resolved before entering the view.

    The RBAC middleware sets ``request.workspace`` from either:
      - the ``workspace_id`` URL kwarg (workspace-scoped URLs), or
      - ``request.user.last_workspace_id`` (global pages such as
        ``/console/intake/`` that have no workspace URL kwarg).

    If neither resolves a workspace the user has access to, this decorator
    returns 403 rather than allowing the view to crash on ``None``.

    Usage::

        @login_required
        @workspace_required
        def my_view(request):
            workspace = request.workspace  # guaranteed non-None here
    """

    @functools.wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request, "workspace", None):
            raise PermissionDenied(
                "A workspace context is required to access this page. "
                "Please ensure you are a member of at least one workspace."
            )
        return view_func(request, *args, **kwargs)

    return _wrapped
