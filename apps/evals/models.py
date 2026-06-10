"""Evals models.

Models:
    EvalCase  — a single evaluation test case for a content agent.
    EvalRun   — a recorded run of an eval suite against an agent.
"""

import uuid

from django.conf import settings
from django.db import models

from apps.common.managers import WorkspaceScopedManager


class EvalCase(models.Model):
    """A single evaluation test case for a content agent (herald/atlas/jarvis)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="eval_cases",
    )

    agent = models.CharField(
        max_length=50,
        help_text="Target agent: herald, atlas, or jarvis",
    )

    description = models.TextField()

    input_fixture = models.JSONField(
        default=dict,
        help_text="JSON fixture representing the input to the agent",
    )

    expected_outcome = models.JSONField(
        default=dict,
        help_text="JSON describing the expected outcome (e.g. {blocked: true})",
    )

    rubric_path = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional path to an external rubric file",
    )

    is_compliance_case = models.BooleanField(
        default=False,
        help_text="True if this case tests a compliance/sensitivity boundary",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eval_cases",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "evals_evalcase"
        ordering = ["created_at"]

    def __str__(self):
        return f"EvalCase[{self.agent}] {self.description[:60]}"


class EvalRun(models.Model):
    """A recorded execution of an eval suite against a specific agent."""

    class Status(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        PARTIAL = "partial", "Partial"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="eval_runs",
    )

    agent = models.CharField(max_length=50)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ERROR,
    )

    total_cases = models.IntegerField(default=0)
    passed = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)

    results_detail = models.JSONField(
        default=list,
        help_text="List of per-case result dicts",
    )

    duration_seconds = models.FloatField(default=0.0)

    triggered_by = models.CharField(max_length=100, default="manual")

    created_at = models.DateTimeField(auto_now_add=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "evals_evalrun"
        ordering = ["-created_at"]

    def __str__(self):
        return f"EvalRun[{self.agent}] {self.status} ({self.passed}/{self.total_cases}) @ {self.created_at:%Y-%m-%d %H:%M}"
