from __future__ import annotations

import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


REQUIRED_COLUMNS: dict[str, list[str]] = {
    "daily_bar": [
        "trade_date",
        "ts_code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
    ],
    "daily_basic": [
        "trade_date",
        "ts_code",
        "pe_ttm",
        "pb",
        "total_mv",
        "turnover_rate",
        "net_mf_amount",
    ],
    "industry": ["trade_date", "ts_code", "industry_code", "industry_name"],
    "financial_indicator": [
        "ann_date",
        "usable_date",
        "ts_code",
        "roe",
        "gross_margin",
        "debt_ratio",
        "revenue_yoy",
        "profit_yoy",
    ],
    "news_event": [
        "stock_code",
        "publish_date",
        "event_type",
        "sentiment",
        "impact_horizon",
        "confidence",
        "reason",
    ],
}


def validate_schema(df: pd.DataFrame, table_name: str) -> None:
    if table_name not in REQUIRED_COLUMNS:
        raise KeyError(f"Unknown table schema: {table_name}")
    require_columns(df, REQUIRED_COLUMNS[table_name], table_name)


def normalize_dates(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col])
    return out
