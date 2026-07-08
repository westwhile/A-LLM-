from __future__ import annotations

import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


def add_adjusted_prices(daily_bar: pd.DataFrame) -> pd.DataFrame:
    require_columns(daily_bar, ["trade_date", "ts_code", "close", "adj_factor"], "daily_bar")
    out = daily_bar.sort_values(["ts_code", "trade_date"]).copy()
    out["adj_close"] = out["close"] * out["adj_factor"]
    out["return_1d"] = out.groupby("ts_code")["adj_close"].pct_change()
    return out


def add_forward_returns(
    daily_bar: pd.DataFrame,
    horizon: int = 20,
    price_col: str = "adj_close",
) -> pd.DataFrame:
    require_columns(daily_bar, ["trade_date", "ts_code", price_col], "daily_bar")
    out = daily_bar.sort_values(["ts_code", "trade_date"]).copy()
    future_price = out.groupby("ts_code")[price_col].shift(-horizon)
    out[f"future_return_{horizon}"] = future_price / out[price_col] - 1
    return out


def filter_universe(
    daily_bar: pd.DataFrame,
    min_amount_20: float | None = None,
) -> pd.DataFrame:
    """Apply basic sample-safe universe filters.

    TODO: replace sample flags with point-in-time historical index membership,
    ST status, suspensions, delistings, and limit-up/down tradability checks.
    """

    out = daily_bar.copy()
    mask = pd.Series(True, index=out.index)
    if "is_suspended" in out:
        mask &= ~out["is_suspended"].fillna(False).astype(bool)
    if "is_st" in out:
        mask &= ~out["is_st"].fillna(False).astype(bool)
    if min_amount_20 is not None:
        avg_amount = (
            out.sort_values(["ts_code", "trade_date"])
            .groupby("ts_code")["amount"]
            .transform(lambda s: s.rolling(20, min_periods=5).mean())
        )
        mask &= avg_amount >= min_amount_20
    return out.loc[mask].copy()
