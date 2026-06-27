"""Test fixtures for the calendar app.

Re-exports the shared ``make_user_in_workspace`` builder defined for the
role-aware Home tests (``apps/home/tests/conftest.py``) so the calendar
render-smoke test can attach a user to the root ``workspace`` fixture with a
specific workspace role — exactly the pattern ``apps/accounts/tests/conftest.py``
already uses.
"""
from apps.home.tests.conftest import make_user_in_workspace  # noqa: F401
