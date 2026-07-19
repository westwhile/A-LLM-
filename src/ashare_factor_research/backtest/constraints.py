from __future__ import annotations

import pandas as pd


def exchange_limit_rate(ts_code: str, trade_date, is_st: bool = False) -> float:
    """Return the ordinary daily price-limit rate for common A-share boards."""

    if is_st:
        return 0.05
    code = str(ts_code).split(".")[0]
    date = pd.Timestamp(trade_date)
    if code.startswith("688"):
        return 0.20
    if code.startswith("300") and date >= pd.Timestamp("2020-08-24"):
        return 0.20
    if code.startswith(("8", "4")):
        return 0.30
    return 0.10


def mark_tradability(
    daily_bar: pd.DataFrame,
    *,
    exclude_limit_up_for_buy: bool = True,
    exclude_limit_down_for_sell: bool = True,
) -> pd.DataFrame:
    """Create auditable buy/sell flags, preferring supplied PIT limit prices."""

    out = daily_bar.copy()
    out["can_buy"] = True
    out["can_sell"] = True
    if "is_suspended" in out:
        suspended = out["is_suspended"].fillna(False).astype(bool)
        out.loc[suspended, ["can_buy", "can_sell"]] = False
    if {"ts_code", "trade_date", "prev_close"}.issubset(out.columns):
        rates = [exchange_limit_rate(code, date, bool(st)) for code, date, st in zip(
            out["ts_code"], out["trade_date"], out.get("is_st", pd.Series(False, index=out.index))
        )]
        rates = pd.Series(rates, index=out.index)
        if "up_limit" not in out:
            out["up_limit"] = out["prev_close"].astype(float) * (1 + rates)
        if "down_limit" not in out:
            out["down_limit"] = out["prev_close"].astype(float) * (1 - rates)
    special = out.get("is_ipo_no_limit", pd.Series(False, index=out.index)).fillna(False).astype(bool)
    special |= out.get("is_relisting_no_limit", pd.Series(False, index=out.index)).fillna(False).astype(bool)
    if exclude_limit_up_for_buy and {"open", "up_limit"}.issubset(out.columns):
        out.loc[(out["open"] >= out["up_limit"]) & ~special, "can_buy"] = False
    if exclude_limit_down_for_sell and {"open", "down_limit"}.issubset(out.columns):
        out.loc[(out["open"] <= out["down_limit"]) & ~special, "can_sell"] = False
    if "is_delisting_period" in out:
        out.loc[out["is_delisting_period"].fillna(False).astype(bool), "can_buy"] = False
    return out


def trade_block_reason(row: pd.Series, side: str) -> str:
    if bool(row.get("is_suspended", False)):
        return "suspended"
    if side == "buy" and not bool(row.get("can_buy", True)):
        return "limit_up"
    if side == "sell" and not bool(row.get("can_sell", True)):
        return "limit_down"
    return ""
