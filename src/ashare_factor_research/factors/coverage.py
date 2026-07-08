from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def factor_coverage_by_date(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    date_col: str = "trade_date",
) -> pd.DataFrame:
    require_columns(factor_df, [date_col], "factor_df")
    rows: list[pd.DataFrame] = []
    for factor in factor_cols:
        if factor not in factor_df:
            continue
        coverage = factor_df.groupby(date_col)[factor].agg(total="size", non_missing="count")
        coverage["coverage"] = coverage["non_missing"] / coverage["total"].replace(0, np.nan)
        coverage["factor"] = factor
        rows.append(coverage.reset_index())
    if not rows:
        return pd.DataFrame(columns=[date_col, "factor", "total", "non_missing", "coverage"])
    return pd.concat(rows, ignore_index=True)[[date_col, "factor", "total", "non_missing", "coverage"]]


def factor_coverage_by_industry(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    date_col: str = "trade_date",
    industry_col: str = "industry_code",
) -> pd.DataFrame:
    require_columns(factor_df, [date_col, industry_col], "factor_df")
    rows: list[pd.DataFrame] = []
    for factor in factor_cols:
        if factor not in factor_df:
            continue
        coverage = factor_df.groupby([date_col, industry_col])[factor].agg(total="size", non_missing="count")
        coverage["coverage"] = coverage["non_missing"] / coverage["total"].replace(0, np.nan)
        coverage["factor"] = factor
        rows.append(coverage.reset_index())
    if not rows:
        return pd.DataFrame(columns=[date_col, industry_col, "factor", "total", "non_missing", "coverage"])
    return pd.concat(rows, ignore_index=True)[[date_col, industry_col, "factor", "total", "non_missing", "coverage"]]


def factor_coverage_by_size_bucket(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    date_col: str = "trade_date",
    size_col: str = "size",
    n_buckets: int = 5,
) -> pd.DataFrame:
    require_columns(factor_df, [date_col, size_col], "factor_df")
    df = factor_df.copy()
    df["size_bucket"] = df.groupby(date_col)[size_col].transform(
        lambda s: pd.qcut(s.rank(method="first"), q=min(n_buckets, s.notna().sum()), labels=False, duplicates="drop")
        if s.notna().sum() >= 2
        else np.nan
    )
    rows: list[pd.DataFrame] = []
    for factor in factor_cols:
        if factor not in df:
            continue
        coverage = df.groupby([date_col, "size_bucket"], dropna=False)[factor].agg(total="size", non_missing="count")
        coverage["coverage"] = coverage["non_missing"] / coverage["total"].replace(0, np.nan)
        coverage["factor"] = factor
        rows.append(coverage.reset_index())
    if not rows:
        return pd.DataFrame(columns=[date_col, "size_bucket", "factor", "total", "non_missing", "coverage"])
    return pd.concat(rows, ignore_index=True)[[date_col, "size_bucket", "factor", "total", "non_missing", "coverage"]]


def factor_missing_streaks(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    date_col: str = "trade_date",
    asset_col: str = "ts_code",
) -> pd.DataFrame:
    require_columns(factor_df, [date_col, asset_col], "factor_df")
    rows: list[dict[str, object]] = []
    ordered = factor_df.sort_values([asset_col, date_col])
    for factor in factor_cols:
        if factor not in ordered:
            continue
        for code, part in ordered.groupby(asset_col):
            streak = 0
            max_streak = 0
            for is_missing in part[factor].isna():
                streak = streak + 1 if is_missing else 0
                max_streak = max(max_streak, streak)
            rows.append({"ts_code": code, "factor": factor, "max_missing_streak": max_streak})
    return pd.DataFrame(rows, columns=["ts_code", "factor", "max_missing_streak"])


def audit_factor_coverage(
    factor_df: pd.DataFrame,
    factor_cols: list[str],
    date_col: str = "trade_date",
    asset_col: str = "ts_code",
    industry_col: str = "industry_code",
    size_col: str = "size",
) -> dict[str, pd.DataFrame]:
    return {
        "by_date": factor_coverage_by_date(factor_df, factor_cols, date_col=date_col),
        "by_industry": factor_coverage_by_industry(factor_df, factor_cols, date_col=date_col, industry_col=industry_col)
        if industry_col in factor_df
        else pd.DataFrame(),
        "by_size_bucket": factor_coverage_by_size_bucket(factor_df, factor_cols, date_col=date_col, size_col=size_col)
        if size_col in factor_df
        else pd.DataFrame(),
        "missing_streaks": factor_missing_streaks(factor_df, factor_cols, date_col=date_col, asset_col=asset_col),
    }
