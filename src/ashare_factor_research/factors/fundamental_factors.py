from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns, safe_divide


def align_financial_to_dates(
    trade_dates: pd.DatetimeIndex,
    financial_indicator: pd.DataFrame,
) -> pd.DataFrame:
    require_columns(
        financial_indicator,
        ["usable_date", "ts_code", "roe", "gross_margin", "debt_ratio", "revenue_yoy", "profit_yoy"],
        "financial_indicator",
    )
    rows = []
    fin = financial_indicator.sort_values(["ts_code", "usable_date"]).copy()
    for code, stock_fin in fin.groupby("ts_code"):
        stock_fin = stock_fin.set_index("usable_date")
        aligned = stock_fin.reindex(trade_dates, method="ffill")
        aligned["trade_date"] = trade_dates
        aligned["ts_code"] = code
        rows.append(aligned.reset_index(drop=True))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def compute_fundamental_factors(
    daily_basic: pd.DataFrame,
    financial_indicator: pd.DataFrame,
    trade_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    require_columns(daily_basic, ["trade_date", "ts_code", "pe_ttm", "pb", "total_mv"], "daily_basic")
    basic = daily_basic.copy()
    basic["size"] = np.log(basic["total_mv"].where(basic["total_mv"] > 0))
    basic["bp"] = safe_divide(pd.Series(1.0, index=basic.index), basic["pb"])
    basic["ep"] = safe_divide(pd.Series(1.0, index=basic.index), basic["pe_ttm"])

    aligned_fin = align_financial_to_dates(trade_dates, financial_indicator)
    keep = ["trade_date", "ts_code", "roe", "gross_margin", "debt_ratio", "revenue_yoy", "profit_yoy"]
    merged = basic.merge(aligned_fin[keep], on=["trade_date", "ts_code"], how="left")
    return merged[
        [
            "trade_date",
            "ts_code",
            "size",
            "bp",
            "ep",
            "roe",
            "gross_margin",
            "debt_ratio",
            "revenue_yoy",
            "profit_yoy",
        ]
    ]
