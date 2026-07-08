from __future__ import annotations

import pandas as pd

from ashare_factor_research.utils.helpers import require_columns, safe_divide


def compute_money_flow_factors(daily_basic: pd.DataFrame, daily_bar: pd.DataFrame) -> pd.DataFrame:
    require_columns(daily_basic, ["trade_date", "ts_code", "net_mf_amount"], "daily_basic")
    require_columns(daily_bar, ["trade_date", "ts_code", "amount"], "daily_bar")
    basic_cols = ["trade_date", "ts_code", "net_mf_amount"]
    if "large_order_net_mf_amount" in daily_basic:
        basic_cols.append("large_order_net_mf_amount")
    df = daily_basic[basic_cols].merge(
        daily_bar[["trade_date", "ts_code", "amount"]],
        on=["trade_date", "ts_code"],
        how="left",
    )
    df = df.sort_values(["ts_code", "trade_date"])
    df["mf_ratio"] = safe_divide(df["net_mf_amount"], df["amount"])
    df["mf_5"] = df.groupby("ts_code")["mf_ratio"].transform(
        lambda s: s.rolling(5, min_periods=3).sum()
    )
    df["mf_20"] = df.groupby("ts_code")["mf_ratio"].transform(
        lambda s: s.rolling(20, min_periods=10).sum()
    )
    if "large_order_net_mf_amount" in df:
        df["large_order_mf_ratio"] = safe_divide(df["large_order_net_mf_amount"], df["amount"])
        df["large_order_mf_20"] = df.groupby("ts_code")["large_order_mf_ratio"].transform(
            lambda s: s.rolling(20, min_periods=10).sum()
        )
    else:
        df["large_order_mf_20"] = pd.NA
    return df[["trade_date", "ts_code", "mf_5", "mf_20", "large_order_mf_20"]]
