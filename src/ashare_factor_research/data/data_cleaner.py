from __future__ import annotations

import pandas as pd

from ashare_factor_research.data.trading_calendar import next_trade_date
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


def compute_usable_dates(
    financial_indicator: pd.DataFrame,
    trade_dates: pd.DatetimeIndex,
    ann_date_col: str = "ann_date",
) -> pd.DataFrame:
    """Attach the first tradable date after each announcement date."""

    require_columns(financial_indicator, [ann_date_col], "financial_indicator")
    out = financial_indicator.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(trade_dates).sort_values().unique())
    out[ann_date_col] = pd.to_datetime(out[ann_date_col])
    out["usable_date"] = [next_trade_date(dates, date) for date in out[ann_date_col]]
    return out


def validate_point_in_time(
    df: pd.DataFrame,
    signal_date_col: str = "trade_date",
    usable_date_col: str = "usable_date",
) -> None:
    """Raise if any row uses information unavailable on the signal date."""

    require_columns(df, [signal_date_col, usable_date_col], "point_in_time_frame")
    signal_dates = pd.to_datetime(df[signal_date_col])
    usable_dates = pd.to_datetime(df[usable_date_col])
    leaked = usable_dates.notna() & signal_dates.notna() & (usable_dates > signal_dates)
    if leaked.any():
        sample = df.loc[leaked, [signal_date_col, usable_date_col]].head(5).to_dict("records")
        raise ValueError(f"Found point-in-time leakage: usable_date after signal date. Sample: {sample}")


def active_index_members(
    index_member: pd.DataFrame,
    signal_date: pd.Timestamp,
    index_code: str | None = None,
) -> set[str]:
    require_columns(index_member, ["index_code", "ts_code", "in_date", "out_date"], "index_member")
    members = index_member.copy()
    members["in_date"] = pd.to_datetime(members["in_date"])
    members["out_date"] = pd.to_datetime(members["out_date"])
    date = pd.Timestamp(signal_date)
    mask = (members["in_date"] <= date) & (members["out_date"].isna() | (date < members["out_date"]))
    if index_code is not None:
        mask &= members["index_code"].eq(index_code)
    return set(members.loc[mask, "ts_code"].astype(str))


def add_limit_tradability(daily_bar: pd.DataFrame) -> pd.DataFrame:
    require_columns(daily_bar, ["open", "up_limit", "down_limit"], "daily_bar")
    out = daily_bar.copy()
    if "is_suspended" in out:
        suspended = out["is_suspended"].fillna(False).astype(bool)
    else:
        suspended = pd.Series(False, index=out.index)
    out["can_buy_open"] = (~suspended) & (out["open"] < out["up_limit"])
    out["can_sell_open"] = (~suspended) & (out["open"] > out["down_limit"])
    return out


def filter_universe(
    daily_bar: pd.DataFrame,
    stock_basic: pd.DataFrame | None = None,
    index_member: pd.DataFrame | None = None,
    st_status: pd.DataFrame | None = None,
    suspension: pd.DataFrame | None = None,
    index_code: str | None = None,
    trade_dates: pd.DatetimeIndex | None = None,
    min_list_days: int = 120,
    min_amount_20: float | None = None,
    exclude_st: bool = True,
    exclude_suspended: bool = True,
) -> pd.DataFrame:
    """Apply point-in-time universe filters when reference tables are available."""

    out = daily_bar.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    mask = pd.Series(True, index=out.index)
    if exclude_suspended and "is_suspended" in out:
        mask &= ~out["is_suspended"].fillna(False).astype(bool)
    if exclude_st and "is_st" in out:
        mask &= ~out["is_st"].fillna(False).astype(bool)
    if stock_basic is not None and not stock_basic.empty:
        require_columns(stock_basic, ["ts_code", "list_date", "delist_date"], "stock_basic")
        basic = stock_basic[["ts_code", "list_date", "delist_date"]].copy()
        basic["list_date"] = pd.to_datetime(basic["list_date"])
        basic["delist_date"] = pd.to_datetime(basic["delist_date"])
        out = out.merge(basic, on="ts_code", how="left")
        if trade_dates is not None:
            ordered_dates = pd.DatetimeIndex(pd.to_datetime(trade_dates).sort_values().unique())
            date_pos = pd.Series(range(len(ordered_dates)), index=ordered_dates)
            trade_pos = out["trade_date"].map(date_pos)

            def _first_list_pos(date: pd.Timestamp) -> object:
                if pd.isna(date):
                    return pd.NA
                valid_dates = ordered_dates[ordered_dates >= date]
                return date_pos.loc[valid_dates[0]] if len(valid_dates) else pd.NA

            list_pos = out["list_date"].map(_first_list_pos)
            list_age = trade_pos.astype("Float64") - list_pos.astype("Float64")
            mask &= list_age >= min_list_days
        else:
            mask &= (out["trade_date"] - out["list_date"]).dt.days >= min_list_days
        mask &= out["delist_date"].isna() | (out["trade_date"] < out["delist_date"])
    if index_member is not None and not index_member.empty:
        member_mask = pd.Series(False, index=out.index)
        for date, idx in out.groupby("trade_date").groups.items():
            active = active_index_members(index_member, pd.Timestamp(date), index_code=index_code)
            member_mask.loc[idx] = out.loc[idx, "ts_code"].isin(active).to_numpy()
        mask &= member_mask
    if exclude_st and st_status is not None and not st_status.empty:
        require_columns(st_status, ["ts_code", "start_date", "end_date"], "st_status")
        st = st_status.copy()
        st["start_date"] = pd.to_datetime(st["start_date"])
        st["end_date"] = pd.to_datetime(st["end_date"])
        st_mask = pd.Series(False, index=out.index)
        for date, idx in out.groupby("trade_date").groups.items():
            active = st[(st["start_date"] <= date) & (st["end_date"].isna() | (date < st["end_date"]))]
            st_mask.loc[idx] = out.loc[idx, "ts_code"].isin(set(active["ts_code"].astype(str))).to_numpy()
        mask &= ~st_mask
    if exclude_suspended and suspension is not None and not suspension.empty:
        require_columns(suspension, ["ts_code", "suspend_date", "resume_date"], "suspension")
        susp = suspension.copy()
        susp["suspend_date"] = pd.to_datetime(susp["suspend_date"])
        susp["resume_date"] = pd.to_datetime(susp["resume_date"])
        susp_mask = pd.Series(False, index=out.index)
        for date, idx in out.groupby("trade_date").groups.items():
            active = susp[
                (susp["suspend_date"] <= date) & (susp["resume_date"].isna() | (date < susp["resume_date"]))
            ]
            susp_mask.loc[idx] = out.loc[idx, "ts_code"].isin(set(active["ts_code"].astype(str))).to_numpy()
        mask &= ~susp_mask
    if min_amount_20 is not None:
        avg_amount = (
            out.sort_values(["ts_code", "trade_date"])
            .groupby("ts_code")["amount"]
            .transform(lambda s: s.rolling(20, min_periods=5).mean())
        )
        mask &= avg_amount >= min_amount_20
    return out.loc[mask].copy()
