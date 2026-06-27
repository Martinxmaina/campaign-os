"""Test fixtures for the accounts app.

Re-exports the shared ``make_user_in_workspace`` builder defined for the
role-aware Home tests (``apps/home/tests/conftest.py``) so the default-landing
redirect test can attach a user to the root ``workspace`` fixture with a
specific workspace role — exactly the pattern that suite already uses.
"""
from apps.home.tests.conftest import make_user_in_workspace  # noqa: F401
