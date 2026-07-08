from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def calc_ic(
    factor_df: pd.DataFrame,
    factor_col: str,
    return_col: str,
    date_col: str = "trade_date",
    method: str = "spearman",
) -> pd.Series:
    require_columns(factor_df, [date_col, factor_col, return_col], "factor_df")
    values: dict[pd.Timestamp, float] = {}
    for date, part in factor_df.groupby(date_col):
        use = part[[factor_col, return_col]].dropna()
        if len(use) < 3:
            values[pd.Timestamp(date)] = np.nan
        else:
            if method == "spearman":
                x = use[factor_col].rank(method="average")
                y = use[return_col].rank(method="average")
                values[pd.Timestamp(date)] = float(x.corr(y, method="pearson"))
            else:
                values[pd.Timestamp(date)] = float(use[factor_col].corr(use[return_col], method=method))
    return pd.Series(values, name=f"{factor_col}_{method}_ic").sort_index()


def summarize_ic(ic_series: pd.Series) -> dict[str, float]:
    clean = ic_series.dropna()
    if clean.empty:
        return {"mean": np.nan, "std": np.nan, "icir": np.nan, "hit_rate": np.nan, "t_stat": np.nan, "count": 0.0}
    std = clean.std(ddof=1)
    mean = clean.mean()
    se = std / np.sqrt(len(clean)) if std and not np.isnan(std) else np.nan
    return {
        "mean": float(mean),
        "std": float(std),
        "icir": float(mean / std) if std and not np.isnan(std) else np.nan,
        "hit_rate": float((clean > 0).mean()),
        "t_stat": float(mean / se) if se and not np.isnan(se) else np.nan,
        "count": float(len(clean)),
    }


def calc_factor_ic_table(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    return_col: str,
    method: str = "spearman",
) -> pd.DataFrame:
    rows = []
    for col in factor_cols:
        summary = summarize_ic(calc_ic(factor_df, col, return_col, method=method))
        summary["factor"] = col
        rows.append(summary)
    return pd.DataFrame(rows).set_index("factor")
