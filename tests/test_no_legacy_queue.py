import pathlib
import subprocess


def test_no_background_task_references():
    root = pathlib.Path(__file__).resolve().parent.parent
    out = subprocess.run(
        ["grep", "-rIn", "-E", r"background_task|@background|process_tasks",
         "--include=*.py", "--include=Procfile", "--include=*.yaml", "--include=*.json",
         str(root / "apps"), str(root / "config"), str(root / "Procfile"),
         str(root / "render.yaml"), str(root / "app.json")],
        capture_output=True, text=True,
    )
    # grep exit 1 == no matches == pass
    assert out.returncode == 1, f"legacy queue references remain:\n{out.stdout}"
