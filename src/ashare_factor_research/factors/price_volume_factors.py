from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns, safe_divide


def compute_price_volume_factors(daily_bar: pd.DataFrame) -> pd.DataFrame:
    require_columns(
        daily_bar,
        ["trade_date", "ts_code", "adj_close", "return_1d", "amount"],
        "daily_bar",
    )
    out = daily_bar.sort_values(["ts_code", "trade_date"]).copy()
    g = out.groupby("ts_code", group_keys=False)
    out["mom_20"] = g["adj_close"].pct_change(20)
    out["mom_60_skip5"] = g["adj_close"].shift(5) / g["adj_close"].shift(60) - 1
    out["rev_5"] = -g["adj_close"].pct_change(5)
    out["vol_20"] = g["return_1d"].transform(lambda s: s.rolling(20, min_periods=10).std())
    out["turnover_20"] = (
        g["turnover_rate"].transform(lambda s: s.rolling(20, min_periods=10).mean())
        if "turnover_rate" in out
        else np.nan
    )
    amihud_raw = safe_divide(out["return_1d"].abs(), out["amount"])
    out["amihud_20"] = amihud_raw.groupby(out["ts_code"]).transform(
        lambda s: s.rolling(20, min_periods=10).mean()
    )
    return out[
        [
            "trade_date",
            "ts_code",
            "mom_20",
            "mom_60_skip5",
            "rev_5",
            "vol_20",
            "turnover_20",
            "amihud_20",
        ]
    ]
