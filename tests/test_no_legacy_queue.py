import json
import pathlib
import subprocess


def test_app_json_has_beat_formation():
    """app.json must declare a beat process so Heroku one-click deploy runs it."""
    root = pathlib.Path(__file__).resolve().parent.parent
    data = json.loads((root / "app.json").read_text())
    formation = data.get("formation", {})
    assert "beat" in formation, (
        "app.json formation is missing 'beat' entry — Heroku one-click deploys will "
        "start beat at quantity 0 and periodic work (publish-cycle, sweeps) will never run."
    )
    assert formation["beat"].get("quantity", 0) >= 1, (
        "app.json formation beat.quantity must be >= 1"
    )


def test_readme_deploy_table_mentions_beat():
    """README Deployment section must document that the Celery beat scheduler runs.

    Campaign OS deploys on Railway as a single Docker image, role-selected by
    PROCESS_TYPE (web | worker); the worker role runs beat. This guards against
    a future edit dropping beat from the deploy docs and silently stranding all
    periodic jobs (sheet sync, calendar scan, health checks).
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    errors = []

    if "## Deployment" not in readme:
        errors.append("README has no '## Deployment' section")

    worker_row = None
    for line in readme.splitlines():
        stripped = line.strip()
        if stripped.startswith("| `worker`"):
            worker_row = stripped
            break
    if worker_row is None:
        errors.append("README Deployment table: no `worker` PROCESS_TYPE row found")
    elif "beat" not in worker_row.lower():
        errors.append(f"README `worker` row does not mention 'beat': {worker_row!r}")

    if "redis" not in readme.lower():
        errors.append("README Deployment section does not mention Redis")

    assert not errors, "\n".join(errors)


def test_no_background_task_references():
    root = pathlib.Path(__file__).resolve().parent.parent
    out = subprocess.run(
        ["grep", "-rIn", "-E", r"background_task|@background|process_tasks",
         # Scan the whole repo root so cutover misses in the Docker/Railway
         # launch path (docker-entrypoint.sh, docker-compose.yml, Dockerfile)
         # and dependency manifests are caught — that path is the primary
         # one in production. Exclude VCS/venv/cache dirs and tests/ (the
         # latter contains this gate's own pattern string).
         "--exclude-dir=.git", "--exclude-dir=.venv", "--exclude-dir=venv",
         "--exclude-dir=node_modules", "--exclude-dir=__pycache__",
         "--exclude-dir=tests", "--exclude-dir=.pytest_cache",
         str(root)],
        capture_output=True, text=True,
    )
    # grep exit 1 == no matches == pass
    assert out.returncode == 1, f"legacy queue references remain:\n{out.stdout}"
