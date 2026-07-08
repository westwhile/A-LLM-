from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def winsorize_mad(
    df: pd.DataFrame,
    factor_col: str,
    date_col: str = "trade_date",
    n: float = 3.0,
) -> pd.DataFrame:
    require_columns(df, [date_col, factor_col], "factor_df")
    out = df.copy()

    def clip_one(s: pd.Series) -> pd.Series:
        median = s.median(skipna=True)
        mad = (s - median).abs().median(skipna=True)
        if pd.isna(mad) or mad == 0:
            return s
        lower = median - n * 1.4826 * mad
        upper = median + n * 1.4826 * mad
        return s.clip(lower, upper)

    out[factor_col] = out.groupby(date_col)[factor_col].transform(clip_one)
    return out


def zscore_by_date(df: pd.DataFrame, factor_col: str, date_col: str = "trade_date") -> pd.DataFrame:
    require_columns(df, [date_col, factor_col], "factor_df")
    out = df.copy()

    def zscore(s: pd.Series) -> pd.Series:
        std = s.std(skipna=True, ddof=0)
        if pd.isna(std) or std == 0:
            return s * np.nan
        return (s - s.mean(skipna=True)) / std

    out[factor_col] = out.groupby(date_col)[factor_col].transform(zscore)
    return out


def neutralize_factor(
    df: pd.DataFrame,
    factor_col: str,
    size_col: str,
    industry_col: str,
    date_col: str = "trade_date",
) -> pd.DataFrame:
    require_columns(df, [date_col, factor_col, size_col, industry_col], "factor_df")
    out = df.copy()
    residuals = pd.Series(np.nan, index=out.index, dtype=float)

    for _, part in out.groupby(date_col):
        use = part[[factor_col, size_col, industry_col]].dropna()
        if len(use) < 3 or use[industry_col].nunique() < 1:
            continue
        y = use[factor_col].astype(float).to_numpy()
        size = use[size_col].astype(float)
        size_std = size.std(ddof=0)
        size_x = ((size - size.mean()) / size_std).to_numpy() if size_std else np.zeros(len(size))
        industry_dummies = pd.get_dummies(use[industry_col], drop_first=True, dtype=float)
        x = np.column_stack([np.ones(len(use)), size_x, industry_dummies.to_numpy()])
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        residuals.loc[use.index] = y - x @ beta

    out[factor_col] = residuals
    return out


def process_factors(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    date_col: str = "trade_date",
    size_col: str | None = "size",
    industry_col: str | None = "industry_code",
    winsor_n: float = 3.0,
    neutralize: bool = True,
) -> pd.DataFrame:
    out = factor_df.copy()
    for col in factor_cols:
        out = winsorize_mad(out, col, date_col=date_col, n=winsor_n)
        if (
            neutralize
            and size_col
            and industry_col
            and col != size_col
            and size_col in out
            and industry_col in out
        ):
            out = neutralize_factor(out, col, size_col=size_col, industry_col=industry_col, date_col=date_col)
        out = zscore_by_date(out, col, date_col=date_col)
    return out


def factor_correlation(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    method: str = "spearman",
) -> pd.DataFrame:
    if method == "spearman":
        return factor_df[factor_cols].rank().corr(method="pearson")
    return factor_df[factor_cols].corr(method=method)
