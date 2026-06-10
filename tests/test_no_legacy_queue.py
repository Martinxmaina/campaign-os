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
    """README Other Platforms deploy table rows must each mention beat + Redis."""
    root = pathlib.Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    # Lines 306-308 are the Other Platforms table: each row starts with
    # "| **Platform**" and must mention beat (and Redis for Railway/Render).
    errors = []
    for platform in ("Heroku", "Railway", "Render"):
        # Find the table row that *starts* with this platform name (bold markup)
        row = None
        for line in readme.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"| **{platform}**"):
                row = stripped
                break
        if row is None:
            errors.append(f"README Other Platforms table: no row found for {platform!r}")
            continue
        if "beat" not in row.lower():
            errors.append(f"README Other Platforms table row for {platform!r} does not mention 'beat': {row!r}")
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
