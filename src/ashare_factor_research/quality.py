from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_quality_checks(
    skip_notebooks: bool = False,
    require_ruff: bool = False,
    update_artifacts: bool = False,
) -> list[dict[str, object]]:
    root = project_root()
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root / "src"), existing_pythonpath) if part
    )
    commands = [
        ("compileall", [sys.executable, "-m", "compileall", "-q", "src", "tests"]),
        ("unittest", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
    ]
    if not skip_notebooks:
        notebook_command = [sys.executable, "scripts/smoke_notebooks.py"]
        if update_artifacts:
            notebook_command.append("--update-artifacts")
        commands.append(("notebook-smoke", notebook_command))
    if importlib.util.find_spec("ruff") is not None:
        commands.append(("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]))
    elif require_ruff:
        raise RuntimeError("ruff is required but not installed")
    rows: list[dict[str, object]] = []
    for name, command in commands:
        completed = subprocess.run(command, cwd=root, env=env, check=False)
        rows.append({"name": name, "returncode": completed.returncode, "command": command})
        if completed.returncode:
            raise RuntimeError(f"Quality step failed: {name}")
    with tempfile.TemporaryDirectory(prefix="ashare_cli_") as tmp:
        data_dir = Path(tmp) / "data"
        run_dir = Path(tmp) / "runs"
        for name, command in [
            ("cli-generate", [sys.executable, "-m", "ashare_factor_research.main", "generate-sample", "--output-dir", str(data_dir)]),
            ("cli-pipeline", [sys.executable, "-m", "ashare_factor_research.main", "run-pipeline", "--mode", "sample", "--data-dir", str(data_dir), "--output-dir", str(run_dir), "--run-id", "quality-smoke"]),
        ]:
            completed = subprocess.run(command, cwd=root, env=env, check=False)
            rows.append({"name": name, "returncode": completed.returncode, "command": command})
            if completed.returncode:
                raise RuntimeError(f"Quality step failed: {name}")
    return rows
