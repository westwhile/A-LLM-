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


def calc_non_overlapping_group_returns(
    factor_df: pd.DataFrame,
    factor_col: str,
    return_col: str,
    rebalance_dates: pd.DatetimeIndex,
    *,
    date_col: str = "trade_date",
    target_end_col: str = "target_return_end_date",
    n_groups: int = 5,
) -> pd.DataFrame:
    """Calculate portfolio-sort returns only on declared non-overlapping signal dates.

    When target-end metadata is present, every holding period must finish before
    the next selected signal date. This prevents overlapping forward labels from
    being silently compounded as a tradable return series.
    """

    dates = pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values().unique()
    selected = factor_df[pd.to_datetime(factor_df[date_col]).isin(dates)].copy()
    if target_end_col in selected and not selected.empty:
        timing = (
            selected.assign(**{date_col: pd.to_datetime(selected[date_col]), target_end_col: pd.to_datetime(selected[target_end_col])})
            .groupby(date_col, as_index=False)[target_end_col]
            .max()
            .sort_values(date_col)
        )
        next_signal = timing[date_col].shift(-1)
        overlap = timing[target_end_col].ge(next_signal) & next_signal.notna()
        if overlap.any():
            sample = timing.loc[overlap, [date_col, target_end_col]].head(3).to_dict("records")
            raise ValueError(f"Selected group-test holding periods overlap: {sample}")
    result = calc_group_returns(selected, factor_col, return_col, date_col=date_col, n_groups=n_groups)
    result.index = pd.to_datetime(result.index)
    result.index.name = date_col
    return result


def calc_group_counts(
    factor_df: pd.DataFrame,
    factor_col: str,
    date_col: str = "trade_date",
    n_groups: int = 5,
) -> pd.DataFrame:
    require_columns(factor_df, [date_col, factor_col], "factor_df")
    out = factor_df.copy()
    out["group"] = assign_quantile_groups(out, factor_col, date_col, n_groups)
    counts = out.dropna(subset=["group"]).groupby([date_col, "group"]).size().unstack("group").sort_index()
    counts.columns = [f"Q{int(c)}" for c in counts.columns]
    return counts


def calc_group_cumulative_returns(group_returns: pd.DataFrame) -> pd.DataFrame:
    return_cols = [col for col in group_returns.columns if str(col).startswith("Q")]
    out = (1.0 + group_returns[return_cols].fillna(0.0)).cumprod()
    out.index = pd.to_datetime(out.index)
    return out


def calc_group_monotonicity(group_returns: pd.DataFrame, n_groups: int = 5) -> dict[str, float]:
    group_cols = [f"Q{i}" for i in range(1, n_groups + 1) if f"Q{i}" in group_returns.columns]
    if len(group_cols) < 2:
        return {"monotonic_score": np.nan, "mean_spearman_by_group": np.nan}
    means = group_returns[group_cols].mean()
    score = float((means.diff().dropna() > 0).mean())
    ranks = pd.Series(range(1, len(means) + 1), index=means.index)
    return {
        "monotonic_score": score,
        "mean_spearman_by_group": float(ranks.corr(means.rank(method="average"), method="pearson")),
    }


def calc_group_turnover(
    factor_df: pd.DataFrame,
    factor_col: str,
    asset_col: str = "ts_code",
    date_col: str = "trade_date",
    n_groups: int = 5,
) -> pd.DataFrame:
    require_columns(factor_df, [date_col, asset_col, factor_col], "factor_df")
    out = factor_df[[date_col, asset_col, factor_col]].copy()
    out[date_col] = pd.to_datetime(out[date_col])
    out["group"] = assign_quantile_groups(out, factor_col, date_col, n_groups)
    rows: list[dict[str, object]] = []
    previous: dict[int, set[str]] = {}
    for date, part in out.dropna(subset=["group"]).sort_values(date_col).groupby(date_col):
        for group, group_df in part.groupby("group"):
            group_id = int(group)
            current = set(group_df[asset_col].astype(str))
            prior = previous.get(group_id, set())
            turnover = np.nan if not prior else 1.0 - len(current & prior) / len(current | prior)
            rows.append({"trade_date": pd.Timestamp(date), "group": f"Q{group_id}", "turnover": turnover})
            previous[group_id] = current
    if not rows:
        return pd.DataFrame(columns=["trade_date"])
    return pd.DataFrame(rows).pivot(index="trade_date", columns="group", values="turnover").sort_index()


def calc_group_test_report(
    factor_df: pd.DataFrame,
    factor_col: str,
    return_col: str,
    date_col: str = "trade_date",
    asset_col: str = "ts_code",
    n_groups: int = 5,
) -> dict[str, pd.DataFrame | dict[str, float]]:
    group_returns = calc_group_returns(factor_df, factor_col, return_col, date_col=date_col, n_groups=n_groups)
    return {
        "returns": group_returns,
        "cumulative_returns": calc_group_cumulative_returns(group_returns),
        "counts": calc_group_counts(factor_df, factor_col, date_col=date_col, n_groups=n_groups),
        "turnover": calc_group_turnover(
            factor_df,
            factor_col,
            asset_col=asset_col,
            date_col=date_col,
            n_groups=n_groups,
        ),
        "monotonicity": calc_group_monotonicity(group_returns, n_groups=n_groups),
    }
