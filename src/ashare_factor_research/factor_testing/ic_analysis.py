from __future__ import annotations

import pandas as pd

from ashare_factor_research.factor_testing.ic_test import calc_ic, summarize_ic
from ashare_factor_research.utils.helpers import require_columns


def calc_ic_summary(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    date_col: str = "trade_date",
    method: str = "spearman",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for factor_col in factor_cols:
        row = summarize_ic(calc_ic(factor_df, factor_col, return_col, date_col=date_col, method=method))
        row.update({"factor": factor_col, "return_col": return_col, "method": method})
        rows.append(row)
    return pd.DataFrame(rows).set_index("factor")


def calc_annual_ic_summary(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    date_col: str = "trade_date",
    method: str = "spearman",
) -> pd.DataFrame:
    require_columns(factor_df, [date_col, return_col, *factor_cols], "factor_df")
    out = factor_df.copy()
    out[date_col] = pd.to_datetime(out[date_col])
    rows: list[dict[str, object]] = []
    for year, year_df in out.groupby(out[date_col].dt.year):
        for factor_col in factor_cols:
            row = summarize_ic(calc_ic(year_df, factor_col, return_col, date_col=date_col, method=method))
            row.update({"year": int(year), "factor": factor_col, "return_col": return_col, "method": method})
            rows.append(row)
    return pd.DataFrame(rows)


def calc_rolling_ic_stats(ic_series: pd.Series, window: int = 12) -> pd.DataFrame:
    clean = ic_series.sort_index().astype(float)
    rolling_mean = clean.rolling(window=window, min_periods=max(3, window // 2)).mean()
    rolling_std = clean.rolling(window=window, min_periods=max(3, window // 2)).std(ddof=1)
    out = pd.DataFrame(
        {
            "trade_date": rolling_mean.index,
            "rolling_ic_mean": rolling_mean.to_numpy(),
            "rolling_icir": (rolling_mean / rolling_std).to_numpy(),
            "window": window,
        }
    )
    return out.dropna(subset=["rolling_ic_mean"]).reset_index(drop=True)


def calc_factor_rolling_ic(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    date_col: str = "trade_date",
    method: str = "spearman",
    window: int = 12,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for factor_col in factor_cols:
        ic = calc_ic(factor_df, factor_col, return_col, date_col=date_col, method=method)
        stats = calc_rolling_ic_stats(ic, window=window)
        if not stats.empty:
            stats["factor"] = factor_col
            stats["return_col"] = return_col
            stats["method"] = method
            rows.append(stats)
    if not rows:
        return pd.DataFrame(columns=["trade_date", "rolling_ic_mean", "rolling_icir", "window", "factor"])
    return pd.concat(rows, ignore_index=True)


def infer_market_regime(
    date_returns: pd.Series,
    bull_quantile: float = 0.7,
    bear_quantile: float = 0.3,
) -> pd.Series:
    """Classify date-level returns into bull, bear, and range regimes."""

    clean = date_returns.astype(float).dropna()
    if clean.empty:
        return pd.Series(index=date_returns.index, dtype="object")
    bear = clean.quantile(bear_quantile)
    bull = clean.quantile(bull_quantile)
    return pd.Series(
        pd.cut(
            date_returns,
            bins=[float("-inf"), bear, bull, float("inf")],
            labels=["bear", "range", "bull"],
            include_lowest=True,
        ),
        index=date_returns.index,
        dtype="object",
    )


def calc_regime_ic_summary(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    date_col: str = "trade_date",
    method: str = "spearman",
    regime_col: str | None = None,
    benchmark_return_col: str | None = None,
) -> pd.DataFrame:
    require_columns(factor_df, [date_col, return_col, *factor_cols], "factor_df")
    out = factor_df.copy()
    out[date_col] = pd.to_datetime(out[date_col])
    if regime_col is None:
        if benchmark_return_col is None or benchmark_return_col not in out.columns:
            return pd.DataFrame()
        date_returns = out.groupby(date_col)[benchmark_return_col].last()
        regimes = infer_market_regime(date_returns)
        out["market_regime"] = out[date_col].map(regimes)
        regime_col = "market_regime"
    require_columns(out, [regime_col], "factor_df")
    rows: list[dict[str, object]] = []
    for regime, regime_df in out.dropna(subset=[regime_col]).groupby(regime_col):
        for factor_col in factor_cols:
            row = summarize_ic(calc_ic(regime_df, factor_col, return_col, date_col=date_col, method=method))
            row.update({"regime": str(regime), "factor": factor_col, "return_col": return_col, "method": method})
            rows.append(row)
    return pd.DataFrame(rows)
