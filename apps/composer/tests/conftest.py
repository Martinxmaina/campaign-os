"""Test fixtures for the composer app.

Re-exports the shared ``make_user_in_workspace`` builder defined for the
role-aware Home tests (``apps/home/tests/conftest.py``) so composer tests can
attach a user to the root ``workspace`` fixture with a specific workspace role
— exactly the pattern the Home / accounts suites already use.
"""
from apps.home.tests.conftest import make_user_in_workspace  # noqa: F401
