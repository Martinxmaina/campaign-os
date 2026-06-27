"""Re-export the shared per-role user builder for social_accounts tests.

Mirrors apps/accounts/tests/conftest.py — attaches a user to the root
``workspace`` fixture with a chosen workspace role so RBACMiddleware resolves
``request.workspace_membership``.
"""
from apps.home.tests.conftest import (  # noqa: F401
    make_user_in_workspace,
)
