from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare_factor_research.quality import run_quality_checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-notebooks", action="store_true")
    parser.add_argument("--require-ruff", action="store_true")
    args = parser.parse_args()
    print(run_quality_checks(args.skip_notebooks, args.require_ruff))

