from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NotebookSmokeTest(unittest.TestCase):
    def test_notebooks_are_valid_and_ordered(self) -> None:
        expected = [
            "01_data_collection.ipynb",
            "02_data_cleaning.ipynb",
            "03_factor_construction.ipynb",
            "04_factor_test.ipynb",
            "05_backtest.ipynb",
            "06_risk_attribution.ipynb",
            "07_llm_event_analysis.ipynb",
        ]
        paths = [path.name for path in sorted((ROOT / "notebooks").glob("*.ipynb"))]
        self.assertEqual(paths, expected)
        for name in expected:
            notebook = json.loads((ROOT / "notebooks" / name).read_text(encoding="utf-8"))
            self.assertEqual(notebook["nbformat"], 4)
            code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
            self.assertGreaterEqual(len(code_cells), 1)
            for cell in code_cells:
                compile("".join(cell.get("source", [])), name, "exec")


if __name__ == "__main__":
    unittest.main()
