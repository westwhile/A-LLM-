from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare_factor_research.data.sample_data import write_sample_data


if __name__ == "__main__":
    paths = write_sample_data(ROOT / "data" / "sample")
    for name, path in paths.items():
        print(f"{name}: {path}")
