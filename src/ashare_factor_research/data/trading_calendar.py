from __future__ import annotations

import pandas as pd


def get_trade_dates(daily_bar: pd.DataFrame) -> pd.DatetimeIndex:
    dates = pd.to_datetime(daily_bar["trade_date"].drop_duplicates()).sort_values()
    return pd.DatetimeIndex(dates)


def next_trade_date(trade_dates: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    idx = trade_dates.searchsorted(pd.Timestamp(date), side="right")
    if idx >= len(trade_dates):
        return None
    return trade_dates[idx]


def month_end_rebalance_dates(trade_dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    series = pd.Series(trade_dates, index=trade_dates)
    return pd.DatetimeIndex(series.groupby(series.index.to_period("M")).max().to_list())
