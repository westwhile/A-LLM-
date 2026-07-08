from __future__ import annotations

import pandas as pd

from ashare_factor_research.utils.helpers import require_columns, safe_divide


def compute_money_flow_factors(daily_basic: pd.DataFrame, daily_bar: pd.DataFrame) -> pd.DataFrame:
    require_columns(daily_basic, ["trade_date", "ts_code", "net_mf_amount"], "daily_basic")
    require_columns(daily_bar, ["trade_date", "ts_code", "amount"], "daily_bar")
    df = daily_basic[["trade_date", "ts_code", "net_mf_amount"]].merge(
        daily_bar[["trade_date", "ts_code", "amount"]],
        on=["trade_date", "ts_code"],
        how="left",
    )
    df = df.sort_values(["ts_code", "trade_date"])
    df["mf_ratio"] = safe_divide(df["net_mf_amount"], df["amount"])
    df["mf_20"] = df.groupby("ts_code")["mf_ratio"].transform(
        lambda s: s.rolling(20, min_periods=10).sum()
    )
    return df[["trade_date", "ts_code", "mf_20"]]
