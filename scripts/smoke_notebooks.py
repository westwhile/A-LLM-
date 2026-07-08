from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = ROOT / "notebooks"


def _cell_source(cell: dict[str, object]) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    return str(source)


def run_notebook_smoke(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    namespace: dict[str, object] = {"__name__": "__notebook_smoke__"}
    os.chdir(ROOT)
    for idx, cell in enumerate(notebook.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        exec(compile(_cell_source(cell), str(path), "exec"), namespace)
        print(f"{path.name}: executed code cell {idx}")


def main() -> None:
    notebooks = sorted(NOTEBOOK_DIR.glob("*.ipynb"))
    if not notebooks:
        raise SystemExit("No notebooks found.")
    for notebook in notebooks:
        run_notebook_smoke(notebook)


if __name__ == "__main__":
    main()
