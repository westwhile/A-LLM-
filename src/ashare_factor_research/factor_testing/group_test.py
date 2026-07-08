from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def assign_quantile_groups(
    factor_df: pd.DataFrame,
    factor_col: str,
    date_col: str = "trade_date",
    n_groups: int = 5,
) -> pd.Series:
    require_columns(factor_df, [date_col, factor_col], "factor_df")

    def group_one(s: pd.Series) -> pd.Series:
        valid = s.dropna()
        if valid.nunique() < n_groups:
            return pd.Series(np.nan, index=s.index)
        return pd.qcut(s.rank(method="first"), q=n_groups, labels=False) + 1

    return factor_df.groupby(date_col)[factor_col].transform(group_one)


def calc_group_returns(
    factor_df: pd.DataFrame,
    factor_col: str,
    return_col: str,
    date_col: str = "trade_date",
    n_groups: int = 5,
) -> pd.DataFrame:
    require_columns(factor_df, [date_col, factor_col, return_col], "factor_df")
    out = factor_df.copy()
    out["group"] = assign_quantile_groups(out, factor_col, date_col, n_groups)
    grouped = (
        out.dropna(subset=["group", return_col])
        .groupby([date_col, "group"])[return_col]
        .mean()
        .unstack("group")
        .sort_index()
    )
    grouped.columns = [f"Q{int(c)}" for c in grouped.columns]
    if "Q1" in grouped and f"Q{n_groups}" in grouped:
        grouped[f"Q{n_groups}-Q1"] = grouped[f"Q{n_groups}"] - grouped["Q1"]
    return grouped
