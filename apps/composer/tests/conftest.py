"""Test fixtures for the composer app.

Re-exports the shared ``make_user_in_workspace`` and ``make_post`` builders
defined for the role-aware Home tests (``apps/home/tests/conftest.py``) so
composer tests — including the Phase B compose render-smoke — can attach a user
to the root ``workspace`` fixture with a specific workspace role and build a
draft Post, exactly the pattern the Home / accounts suites already use.
"""
from apps.home.tests.conftest import (  # noqa: F401
    make_post,
    make_user_in_workspace,
)
