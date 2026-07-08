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
    out["market_return"] = out.groupby("trade_date")["return_1d"].transform("mean")
    g = out.groupby("ts_code", group_keys=False)
    out["mom_20"] = g["adj_close"].pct_change(20)
    out["mom_60_skip5"] = g["adj_close"].shift(5) / g["adj_close"].shift(60) - 1
    out["mom_120"] = g["adj_close"].pct_change(120)
    out["rev_5"] = -g["adj_close"].pct_change(5)
    out["rev_20"] = -g["adj_close"].pct_change(20)
    out["vol_20"] = g["return_1d"].transform(lambda s: s.rolling(20, min_periods=10).std())
    out["vol_60"] = g["return_1d"].transform(lambda s: s.rolling(60, min_periods=30).std())
    out["turnover_20"] = (
        g["turnover_rate"].transform(lambda s: s.rolling(20, min_periods=10).mean())
        if "turnover_rate" in out
        else np.nan
    )
    out["turnover_chg_20"] = (
        safe_divide(
            g["turnover_rate"].transform(lambda s: s.rolling(20, min_periods=10).mean()),
            g["turnover_rate"].transform(lambda s: s.rolling(20, min_periods=10).mean().shift(20)),
        )
        - 1
        if "turnover_rate" in out
        else np.nan
    )
    amount_mean_20 = g["amount"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    out["amount_mom_20"] = safe_divide(amount_mean_20, amount_mean_20.groupby(out["ts_code"]).shift(20)) - 1
    amihud_raw = safe_divide(out["return_1d"].abs(), out["amount"])
    out["amihud_20"] = amihud_raw.groupby(out["ts_code"]).transform(
        lambda s: s.rolling(20, min_periods=10).mean()
    )
    out["ret_mkt"] = out["return_1d"] * out["market_return"]
    out["mkt_sq"] = out["market_return"] * out["market_return"]
    mean_ret = g["return_1d"].transform(lambda s: s.rolling(60, min_periods=30).mean())
    mean_mkt = g["market_return"].transform(lambda s: s.rolling(60, min_periods=30).mean())
    mean_ret_mkt = g["ret_mkt"].transform(lambda s: s.rolling(60, min_periods=30).mean())
    mean_mkt_sq = g["mkt_sq"].transform(lambda s: s.rolling(60, min_periods=30).mean())
    beta = safe_divide(mean_ret_mkt - mean_ret * mean_mkt, mean_mkt_sq - mean_mkt * mean_mkt)
    out["beta_60"] = beta
    residual = out["return_1d"] - out["beta_60"] * out["market_return"]
    out["idio_vol_60"] = residual.groupby(out["ts_code"]).transform(
        lambda s: s.rolling(60, min_periods=30).std()
    )
    return out[
        [
            "trade_date",
            "ts_code",
            "mom_20",
            "mom_60_skip5",
            "mom_120",
            "rev_5",
            "rev_20",
            "vol_20",
            "vol_60",
            "beta_60",
            "idio_vol_60",
            "turnover_20",
            "turnover_chg_20",
            "amount_mom_20",
            "amihud_20",
        ]
    ]
