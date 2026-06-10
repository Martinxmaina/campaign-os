import pathlib
import subprocess


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
