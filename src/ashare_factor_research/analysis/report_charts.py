from __future__ import annotations

from pathlib import Path

import pandas as pd

from ashare_factor_research.analysis.drawdown import drawdown_periods
from ashare_factor_research.analysis.performance import monthly_return_matrix, yearly_performance


def save_placeholder_tables(output_dir: str | Path, metrics: dict[str, float], ic_table: pd.DataFrame) -> None:
    """Save text/CSV artifacts when plotting dependencies are unavailable."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.Series(metrics).to_csv(out / "performance_metrics.csv", header=["value"])
    ic_table.to_csv(out / "ic_summary.csv")


def save_performance_report_tables(
    output_dir: str | Path,
    nav_df: pd.DataFrame,
    metrics: dict[str, float],
    trades: pd.DataFrame | None = None,
    cost_summary: pd.DataFrame | None = None,
) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.Series(metrics).to_csv(out / "performance_metrics.csv", header=["value"])
    yearly_performance(nav_df).to_csv(out / "yearly_performance.csv", index=False)
    returns = nav_df.assign(trade_date=pd.to_datetime(nav_df["trade_date"])).set_index("trade_date")["net_return"]
    monthly_return_matrix(returns).to_csv(out / "monthly_returns.csv")
    nav_series = nav_df.assign(trade_date=pd.to_datetime(nav_df["trade_date"])).set_index("trade_date")["nav"]
    drawdown_periods(nav_series).to_csv(out / "drawdown_periods.csv", index=False)
    if trades is not None:
        trades.to_csv(out / "sample_trades.csv", index=False)
    if cost_summary is not None:
        cost_summary.to_csv(out / "cost_attribution.csv", index=False)
