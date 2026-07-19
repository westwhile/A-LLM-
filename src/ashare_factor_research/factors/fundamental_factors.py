from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.utils.helpers import require_columns, safe_divide


def align_financial_to_dates(
    trade_dates: pd.DatetimeIndex,
    financial_indicator: pd.DataFrame,
) -> pd.DataFrame:
    base_columns = ["usable_date", "ts_code", "roe", "gross_margin", "debt_ratio", "revenue_yoy", "profit_yoy"]
    require_columns(
        financial_indicator,
        base_columns,
        "financial_indicator",
    )
    rows = []
    sort_cols = ["ts_code", "usable_date"]
    sort_cols.extend(col for col in ["ann_date", "report_period"] if col in financial_indicator)
    sort_cols.extend(col for col in ["revision_time", "update_time", "revision_id"] if col in financial_indicator)
    fin = financial_indicator.sort_values(sort_cols).copy()
    fin = fin.drop_duplicates(["ts_code", "usable_date"], keep="last")
    fin["financial_usable_date"] = pd.to_datetime(fin["usable_date"])
    if "roe_delta" not in fin:
        fin["roe_delta"] = fin.groupby("ts_code")["roe"].diff()
    if "gross_margin_stability" not in fin:
        gross_margin_vol = fin.groupby("ts_code")["gross_margin"].transform(
            lambda s: s.rolling(4, min_periods=2).std()
        )
        fin["gross_margin_stability"] = -gross_margin_vol
    if "asset_turnover" not in fin and {"operating_revenue", "total_assets"}.issubset(fin.columns):
        fin["asset_turnover"] = safe_divide(fin["operating_revenue"], fin["total_assets"])
    if "roa" not in fin and {"net_profit", "total_assets"}.issubset(fin.columns):
        fin["roa"] = safe_divide(fin["net_profit"], fin["total_assets"])
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
    basic["sp"] = safe_divide(pd.Series(1.0, index=basic.index), basic["ps"]) if "ps" in basic else np.nan

    aligned_fin = align_financial_to_dates(trade_dates, financial_indicator)
    optional_fin_cols = [
        "report_period",
        "ann_date",
        "financial_usable_date",
        "roe",
        "gross_margin",
        "debt_ratio",
        "revenue_yoy",
        "profit_yoy",
        "operating_cash_flow",
        "asset_turnover",
        "roa",
        "gross_margin_stability",
        "roe_delta",
    ]
    keep = ["trade_date", "ts_code"] + [col for col in optional_fin_cols if col in aligned_fin]
    merged = basic.merge(aligned_fin[keep], on=["trade_date", "ts_code"], how="left")
    merged = merged.rename(
        columns={
            "report_period": "financial_report_period",
            "ann_date": "financial_ann_date",
        }
    )
    merged["cfp"] = (
        safe_divide(merged["operating_cash_flow"], merged["total_mv"])
        if "operating_cash_flow" in merged
        else np.nan
    )
    for col in ["asset_turnover", "roa", "gross_margin_stability", "roe_delta"]:
        if col not in merged:
            merged[col] = np.nan
    return merged[
        [
            "trade_date",
            "ts_code",
            "size",
            "bp",
            "ep",
            "sp",
            "cfp",
            "roe",
            "roa",
            "gross_margin",
            "gross_margin_stability",
            "debt_ratio",
            "asset_turnover",
            "revenue_yoy",
            "profit_yoy",
            "roe_delta",
            "financial_report_period",
            "financial_ann_date",
            "financial_usable_date",
        ]
    ]
