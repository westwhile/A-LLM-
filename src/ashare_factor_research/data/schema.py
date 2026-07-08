from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ashare_factor_research.utils.helpers import require_columns


@dataclass(frozen=True)
class TableSchema:
    required_columns: tuple[str, ...]
    primary_key: tuple[str, ...]
    date_columns: tuple[str, ...] = ()
    grain: str = ""


TABLE_SCHEMAS: dict[str, TableSchema] = {
    "trade_calendar": TableSchema(
        required_columns=("trade_date", "is_open"),
        primary_key=("trade_date",),
        date_columns=("trade_date",),
        grain="one row per open trading date",
    ),
    "stock_basic": TableSchema(
        required_columns=("ts_code", "name", "list_date", "delist_date", "exchange"),
        primary_key=("ts_code",),
        date_columns=("list_date", "delist_date"),
        grain="one row per stock security master record",
    ),
    "daily_bar": TableSchema(
        required_columns=(
            "trade_date",
            "ts_code",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adj_factor",
        ),
        primary_key=("trade_date", "ts_code"),
        date_columns=("trade_date",),
        grain="one row per stock trading day",
    ),
    "daily_basic": TableSchema(
        required_columns=(
            "trade_date",
            "ts_code",
            "pe_ttm",
            "pb",
            "total_mv",
            "turnover_rate",
            "net_mf_amount",
        ),
        primary_key=("trade_date", "ts_code"),
        date_columns=("trade_date",),
        grain="one row per stock trading day",
    ),
    "industry": TableSchema(
        required_columns=("trade_date", "ts_code", "industry_code", "industry_name"),
        primary_key=("trade_date", "ts_code"),
        date_columns=("trade_date",),
        grain="one row per stock trading day",
    ),
    "index_member": TableSchema(
        required_columns=("index_code", "ts_code", "weight", "in_date", "out_date"),
        primary_key=("index_code", "ts_code", "in_date"),
        date_columns=("in_date", "out_date"),
        grain="one row per index membership interval",
    ),
    "financial_indicator": TableSchema(
        required_columns=(
            "report_period",
            "ann_date",
            "usable_date",
            "ts_code",
            "roe",
            "gross_margin",
            "debt_ratio",
            "revenue_yoy",
            "profit_yoy",
        ),
        primary_key=("ts_code", "report_period", "ann_date"),
        date_columns=("report_period", "ann_date", "usable_date"),
        grain="one row per stock financial report announcement",
    ),
    "suspension": TableSchema(
        required_columns=("ts_code", "suspend_date", "resume_date"),
        primary_key=("ts_code", "suspend_date"),
        date_columns=("suspend_date", "resume_date"),
        grain="one row per stock suspension interval",
    ),
    "st_status": TableSchema(
        required_columns=("ts_code", "start_date", "end_date"),
        primary_key=("ts_code", "start_date"),
        date_columns=("start_date", "end_date"),
        grain="one row per stock ST interval",
    ),
    "limit_price": TableSchema(
        required_columns=("trade_date", "ts_code", "up_limit", "down_limit"),
        primary_key=("trade_date", "ts_code"),
        date_columns=("trade_date",),
        grain="one row per stock trading day",
    ),
    "benchmark_index": TableSchema(
        required_columns=("trade_date", "index_code", "close"),
        primary_key=("trade_date", "index_code"),
        date_columns=("trade_date",),
        grain="one row per index trading day",
    ),
    "news_event": TableSchema(
        required_columns=(
            "stock_code",
            "publish_date",
            "event_type",
            "sentiment",
            "impact_horizon",
            "confidence",
            "reason",
        ),
        primary_key=("stock_code", "publish_date", "event_type"),
        date_columns=("publish_date",),
        grain="one row per stock event label",
    ),
}

REQUIRED_COLUMNS: dict[str, list[str]] = {
    name: list(schema.required_columns) for name, schema in TABLE_SCHEMAS.items()
}

PRIMARY_KEYS: dict[str, list[str]] = {
    name: list(schema.primary_key) for name, schema in TABLE_SCHEMAS.items()
}

DATE_COLUMNS: dict[str, list[str]] = {
    name: list(schema.date_columns) for name, schema in TABLE_SCHEMAS.items()
}


def get_schema(table_name: str) -> TableSchema:
    if table_name not in TABLE_SCHEMAS:
        raise KeyError(f"Unknown table schema: {table_name}")
    return TABLE_SCHEMAS[table_name]


def validate_schema(df: pd.DataFrame, table_name: str, check_primary_key: bool = False) -> None:
    schema = get_schema(table_name)
    require_columns(df, list(schema.required_columns), table_name)
    if check_primary_key:
        validate_primary_key(df, table_name)


def validate_primary_key(df: pd.DataFrame, table_name: str) -> None:
    schema = get_schema(table_name)
    require_columns(df, list(schema.primary_key), table_name)
    duplicated = df.duplicated(list(schema.primary_key), keep=False)
    if duplicated.any():
        sample = df.loc[duplicated, list(schema.primary_key)].head(5).to_dict("records")
        raise ValueError(
            f"{table_name} primary key is not unique on {list(schema.primary_key)}. "
            f"Duplicate sample: {sample}"
        )


def normalize_dates(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col])
    return out


def normalize_table_dates(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    return normalize_dates(df, DATE_COLUMNS.get(table_name, []))
