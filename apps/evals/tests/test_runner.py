"""Tests for the eval suite runner."""

import pytest

from apps.evals.models import EvalCase, EvalRun
from apps.evals.runner import run_eval_suite


@pytest.mark.django_db
def test_eval_run_records_pass(workspace):
    """Running a dry_run eval on an EvalCase produces a passing EvalRun."""
    EvalCase.objects.create(
        workspace=workspace,
        agent="herald",
        description="Basic dry-run pass test",
        input_fixture={"pillar": "energy", "angle": "Solar growth"},
        expected_outcome={"status": "drafted"},
    )

    run = run_eval_suite(workspace, "herald", dry_run=True)

    assert isinstance(run, EvalRun)
    assert run.workspace == workspace
    assert run.agent == "herald"
    assert run.total_cases == 1
    assert run.passed == 1
    assert run.failed == 0
    assert run.status in (EvalRun.Status.PASSED, EvalRun.Status.FAILED, EvalRun.Status.PARTIAL)
    assert run.triggered_by == "dry_run"
    assert len(run.results_detail) == 1
    assert run.results_detail[0]["passed"] is True


@pytest.mark.django_db
def test_eval_case_for_compliance_edge(workspace):
    """An EvalCase for a compliance boundary can be created and queried."""
    case = EvalCase.objects.create(
        workspace=workspace,
        agent="herald",
        description="Private hold sensitivity — gate must block",
        input_fixture={"sensitivity": "private_hold", "angle": "Confidential donor briefing"},
        expected_outcome={"blocked": True},
        is_compliance_case=True,
    )

    assert case.pk is not None
    assert case.is_compliance_case is True
    assert case.input_fixture["sensitivity"] == "private_hold"
    assert case.expected_outcome["blocked"] is True

    # Run live (not dry_run) — compliance logic should mark it passed
    run = run_eval_suite(workspace, "herald", dry_run=False)

    assert run.total_cases == 1
    assert run.passed == 1
    result = run.results_detail[0]
    assert result["passed"] is True
    assert "compliance" in result["note"]
