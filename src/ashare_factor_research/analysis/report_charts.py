from __future__ import annotations

from pathlib import Path

import pandas as pd


def save_placeholder_tables(output_dir: str | Path, metrics: dict[str, float], ic_table: pd.DataFrame) -> None:
    """Save text/CSV artifacts when plotting dependencies are unavailable."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.Series(metrics).to_csv(out / "performance_metrics.csv", header=["value"])
    ic_table.to_csv(out / "ic_summary.csv")
