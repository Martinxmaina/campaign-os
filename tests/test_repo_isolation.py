import pathlib
import re

# Match only *import statements* that pull in the agent-service Python
# package (its top-level module is ``app``) or any module literally named
# ``agent_service`` / ``agent-service``. Prose, docstrings, comments and
# settings/string references to the agent-service HTTP API are allowed:
# the fork is wired to agent-service over HTTP only, never by import.
PAT = re.compile(
    r"^\s*(from|import)\s+(app|agent[_-]service)\b"
)


def test_no_agent_service_imports():
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for p in root.rglob("*.py"):
        if ".venv" in p.parts or "upstream" in p.parts:
            continue
        for line in p.read_text(errors="ignore").splitlines():
            if PAT.search(line):
                offenders.append(f"{p.relative_to(root)}: {line.strip()}")
    assert offenders == [], f"fork must not import agent-service: {offenders}"
