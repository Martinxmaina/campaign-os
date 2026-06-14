"""Outbound third-party API clients (Google Calendar, Gmail, ...).

These are thin builder/fetch seams kept apart from Django app logic so the
Celery sync tasks in ``apps/joseph/tasks.py`` can patch them in tests without
touching the network. They never persist anything — that is the task's job.
"""
