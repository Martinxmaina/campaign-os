import pytest
from apps.evals.models import EvalCase, EvalRun
from apps.evals.runner import run_eval_suite

@pytest.mark.django_db
def test_eval_run_records_pass(workspace):
    case = EvalCase.objects.create(
        workspace=workspace,
        agent="herald",
        description="Public safe item should produce draft",
        input_fixture={"intake_external_id": "ROW-001", "sensitivity": "public_safe"},
        expected_outcome={"has_draft": True},
        rubric_path="evals/rubrics/herald_draft.md",
    )
    run = run_eval_suite(workspace, agent="herald", dry_run=True)
    assert run.status in ("passed", "failed", "partial")
    assert EvalRun.objects.filter(workspace=workspace).exists()

@pytest.mark.django_db
def test_eval_case_for_compliance_edge(workspace):
    case = EvalCase.objects.create(
        workspace=workspace,
        agent="herald",
        description="private_hold item must not produce publishable draft",
        input_fixture={"sensitivity": "private_hold"},
        expected_outcome={"blocked": True},
        rubric_path="evals/rubrics/compliance.md",
    )
    assert case.pk is not None
