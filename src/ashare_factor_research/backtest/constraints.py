from __future__ import annotations

import pandas as pd


def mark_tradability(daily_bar: pd.DataFrame) -> pd.DataFrame:
    """Create simple buy/sell flags from sample columns.

    TODO: use exchange-specific limit rules, suspension tables, lot sizes,
    volume participation, and delisting treatment for production research.
    """

    out = daily_bar.copy()
    out["can_buy"] = True
    out["can_sell"] = True
    if "is_suspended" in out:
        suspended = out["is_suspended"].fillna(False).astype(bool)
        out.loc[suspended, ["can_buy", "can_sell"]] = False
    if {"open", "up_limit"}.issubset(out.columns):
        out.loc[out["open"] >= out["up_limit"], "can_buy"] = False
    if {"open", "down_limit"}.issubset(out.columns):
        out.loc[out["open"] <= out["down_limit"], "can_sell"] = False
    return out
