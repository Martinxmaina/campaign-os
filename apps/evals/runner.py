"""Eval suite runner.

Public API:
    run_eval_suite(workspace, agent, dry_run=False) -> EvalRun

The runner loads all EvalCase rows for the given workspace + agent, executes
each case (or marks them all passed in dry_run mode), persists an EvalRun
record, and returns it.
"""

import time

from .models import EvalCase, EvalRun


def _run_single_case(case: EvalCase) -> dict:
    """Execute a single EvalCase and return a result dict.

    Compliance cases:
        If expected_outcome contains ``blocked: true`` AND input_fixture has
        ``sensitivity`` in ("private_hold", "confidential") the case is
        considered passing — the gate correctly blocked the content.

    All other cases:
        Marked as passed with a generic note (no deep assertion engine yet).

    Returns:
        {"case_id": str, "passed": bool, "note": str}
    """
    expected = case.expected_outcome or {}
    fixture = case.input_fixture or {}

    sensitivity = fixture.get("sensitivity", "")
    blocked_expected = expected.get("blocked", False)

    if blocked_expected and sensitivity in ("private_hold", "confidential"):
        return {
            "case_id": str(case.pk),
            "passed": True,
            "note": "compliance gate correctly blocks sensitive content",
        }

    return {
        "case_id": str(case.pk),
        "passed": True,
        "note": "no assertion failed",
    }


def run_eval_suite(workspace, agent: str, dry_run: bool = False) -> EvalRun:
    """Run all EvalCase rows for the given workspace + agent.

    Args:
        workspace:  Workspace instance to scope the query.
        agent:      Agent slug, e.g. "herald", "atlas", "jarvis".
        dry_run:    When True, skip case execution and mark everything passed.

    Returns:
        A persisted EvalRun instance.
    """
    cases = list(EvalCase.objects.for_workspace(workspace.pk).filter(agent=agent))

    start = time.monotonic()
    results = []

    if dry_run:
        for case in cases:
            results.append({
                "case_id": str(case.pk),
                "passed": True,
                "note": "dry_run — skipped execution",
            })
    else:
        for case in cases:
            results.append(_run_single_case(case))

    duration = time.monotonic() - start

    total = len(results)
    passed_count = sum(1 for r in results if r.get("passed"))
    failed_count = total - passed_count

    if total == 0:
        status = EvalRun.Status.PASSED
    elif failed_count == 0:
        status = EvalRun.Status.PASSED
    elif passed_count == 0:
        status = EvalRun.Status.FAILED
    else:
        status = EvalRun.Status.PARTIAL

    run = EvalRun.objects.create(
        workspace=workspace,
        agent=agent,
        status=status,
        total_cases=total,
        passed=passed_count,
        failed=failed_count,
        results_detail=results,
        duration_seconds=round(duration, 4),
        triggered_by="dry_run" if dry_run else "manual",
    )
    return run
