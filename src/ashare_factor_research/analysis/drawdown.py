from __future__ import annotations

import numpy as np
import pandas as pd


def drawdown_series(nav: pd.Series) -> pd.Series:
    nav = nav.dropna().astype(float)
    if nav.empty:
        return pd.Series(dtype=float)
    return nav / nav.cummax() - 1.0


def drawdown_periods(nav: pd.Series, top_n: int = 5) -> pd.DataFrame:
    """Return the deepest completed and active drawdown intervals."""

    dd = drawdown_series(nav)
    if dd.empty:
        return pd.DataFrame(columns=["start", "trough", "recovery", "max_drawdown", "duration"])

    periods: list[dict[str, object]] = []
    peak_date = dd.index[0]
    in_drawdown = False
    start = peak_date
    trough = peak_date
    trough_dd = 0.0

    for date, value in dd.items():
        if value == 0.0:
            if in_drawdown:
                periods.append(
                    {
                        "start": start,
                        "trough": trough,
                        "recovery": date,
                        "max_drawdown": float(trough_dd),
                        "duration": _period_distance(dd.index, start, date),
                    }
                )
                in_drawdown = False
            peak_date = date
            start = peak_date
            trough = peak_date
            trough_dd = 0.0
            continue

        if not in_drawdown:
            in_drawdown = True
            start = peak_date
            trough = date
            trough_dd = float(value)
        elif value < trough_dd:
            trough = date
            trough_dd = float(value)

    if in_drawdown:
        periods.append(
            {
                "start": start,
                "trough": trough,
                "recovery": pd.NaT,
                "max_drawdown": float(trough_dd),
                "duration": _period_distance(dd.index, start, dd.index[-1]),
            }
        )

    out = pd.DataFrame(periods)
    if out.empty:
        return pd.DataFrame(columns=["start", "trough", "recovery", "max_drawdown", "duration"])
    return out.sort_values("max_drawdown").head(top_n).reset_index(drop=True)


def max_drawdown_period(nav: pd.Series) -> dict[str, object]:
    periods = drawdown_periods(nav, top_n=1)
    if periods.empty:
        return {
            "start": pd.NaT,
            "trough": pd.NaT,
            "recovery": pd.NaT,
            "max_drawdown": np.nan,
            "duration": 0,
        }
    return periods.iloc[0].to_dict()


def drawdown_contribution(
    contributions: pd.DataFrame,
    start,
    trough,
    date_col: str = "trade_date",
    group_col: str = "ts_code",
    contribution_col: str = "return_contribution",
) -> pd.DataFrame:
    required = {date_col, group_col, contribution_col}
    missing = sorted(required - set(contributions.columns))
    if missing:
        raise ValueError(f"contributions missing required columns: {missing}")
    data = contributions.copy()
    data[date_col] = pd.to_datetime(data[date_col])
    mask = data[date_col].between(pd.Timestamp(start), pd.Timestamp(trough))
    return (
        data.loc[mask]
        .groupby(group_col, as_index=False)[contribution_col]
        .sum()
        .sort_values(contribution_col)
        .reset_index(drop=True)
    )


def _period_distance(index: pd.Index, start, end) -> int:
    positions = pd.Series(range(len(index)), index=index)
    if start not in positions.index or end not in positions.index:
        return 0
    return int(positions.loc[end] - positions.loc[start])
