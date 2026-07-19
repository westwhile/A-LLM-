from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = ROOT / "notebooks"


def _cell_source(cell: dict[str, object]) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    return str(source)


def _redirect_artifacts(source: str, artifact_root: Path) -> str:
    injected = f"ARTIFACT_ROOT = Path(r'{artifact_root}')\n"
    source = source.replace("from pathlib import Path\n", "from pathlib import Path\n" + injected, 1)
    for original, replacement in (
        ("ROOT / 'data' / 'sample'", "ARTIFACT_ROOT / 'data' / 'sample'"),
        ("ROOT / 'reports' / 'notebook_outputs'", "ARTIFACT_ROOT / 'reports' / 'notebook_outputs'"),
        ("ROOT / 'reports' / 'figures'", "ARTIFACT_ROOT / 'reports' / 'figures'"),
    ):
        source = source.replace(original, replacement)
    return source


def run_notebook_smoke(path: Path, artifact_root: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    namespace: dict[str, object] = {"__name__": "__notebook_smoke__"}
    os.chdir(ROOT)
    for idx, cell in enumerate(notebook.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        source = _redirect_artifacts(_cell_source(cell), artifact_root)
        exec(compile(source, str(path), "exec"), namespace)
        print(f"{path.name}: executed code cell {idx}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root")
    parser.add_argument("--update-artifacts", action="store_true")
    args = parser.parse_args()
    notebooks = sorted(NOTEBOOK_DIR.glob("*.ipynb"))
    if not notebooks:
        raise SystemExit("No notebooks found.")
    if args.update_artifacts:
        artifact_root = ROOT
        for notebook in notebooks:
            run_notebook_smoke(notebook, artifact_root)
        return
    if args.output_root:
        artifact_root = Path(args.output_root).resolve()
        artifact_root.mkdir(parents=True, exist_ok=True)
        for notebook in notebooks:
            run_notebook_smoke(notebook, artifact_root)
        return
    with tempfile.TemporaryDirectory(prefix="ashare_notebook_smoke_") as tmp:
        artifact_root = Path(tmp)
        for notebook in notebooks:
            run_notebook_smoke(notebook, artifact_root)


if __name__ == "__main__":
    main()
