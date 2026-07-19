from __future__ import annotations

from pathlib import Path

import pandas as pd

from ashare_factor_research.data.schema import DATE_COLUMNS, PRIMARY_KEYS, REQUIRED_COLUMNS
from ashare_factor_research.utils.io import ensure_dir


NULLABLE_REQUIRED_COLUMNS = {
    ("stock_basic", "delist_date"),
    ("index_member", "out_date"),
    ("suspension", "resume_date"),
    ("st_status", "end_date"),
}

REAL_DATA_EXPECTED_TABLES = {
    "trade_calendar",
    "stock_basic",
    "daily_bar",
    "daily_basic",
    "industry",
    "index_member",
    "financial_indicator",
    "suspension",
    "st_status",
    "limit_price",
    "benchmark_index",
    "news_event",
}


def _issue(table: str, check: str, severity: str, value: object, detail: str) -> dict[str, object]:
    return {
        "table": table,
        "check": check,
        "severity": severity,
        "value": value,
        "detail": detail,
    }


def audit_table(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """Audit one standardized table for schema, keys, ranges, and leakage risks."""

    issues: list[dict[str, object]] = []
    required = REQUIRED_COLUMNS.get(table_name, [])
    primary_key = PRIMARY_KEYS.get(table_name, [])
    date_cols = DATE_COLUMNS.get(table_name, [])

    issues.append(_issue(table_name, "row_count", "info", len(df), "Rows available for audit."))
    missing_required = sorted(set(required) - set(df.columns))
    if missing_required:
        issues.append(
            _issue(
                table_name,
                "required_columns",
                "blocking",
                ",".join(missing_required),
                "Required schema columns are missing.",
            )
        )

    if primary_key and not (set(primary_key) - set(df.columns)):
        duplicate_count = int(df.duplicated(primary_key).sum())
        issues.append(
            _issue(
                table_name,
                "primary_key_duplicates",
                "blocking" if duplicate_count else "ok",
                duplicate_count,
                f"Primary key: {primary_key}.",
            )
        )

    for col in required:
        if col in df.columns:
            missing_rate = float(df[col].isna().mean()) if len(df) else 0.0
            if missing_rate > 0 and (table_name, col) not in NULLABLE_REQUIRED_COLUMNS:
                severity = "blocking" if col in primary_key else "warning"
                issues.append(
                    _issue(
                        table_name,
                        f"missing_rate:{col}",
                        severity,
                        round(missing_rate, 6),
                        "Missing values in required field.",
                    )
                )

    for col in date_cols:
        if col in df.columns and df[col].notna().any():
            dates = pd.to_datetime(df[col], errors="coerce")
            issues.append(
                _issue(
                    table_name,
                    f"date_range:{col}",
                    "info",
                    f"{dates.min().date()}..{dates.max().date()}",
                    "Observed date range.",
                )
            )

    if "ts_code" in df.columns:
        issues.append(
            _issue(table_name, "asset_count", "info", int(df["ts_code"].nunique()), "Unique stock count by ts_code.")
        )

    if table_name == "daily_bar":
        issues.extend(_audit_daily_bar(df, table_name))
    if table_name == "financial_indicator":
        issues.extend(_audit_financial_point_in_time(df, table_name))
    if table_name == "benchmark_index":
        issues.extend(_audit_benchmark(df, table_name))
    if table_name == "news_event" and len(df):
        if "publish_time" not in df.columns:
            issues.append(_issue(
                table_name,
                "publish_time_missing",
                "warning",
                len(df),
                "Date-only events cannot distinguish intraday from after-close publication.",
            ))
        if "sentiment" in df:
            invalid = int((~df["sentiment"].isin(["positive", "neutral", "negative"])).sum())
            issues.append(_issue(table_name, "sentiment_enum", "blocking" if invalid else "ok", invalid, "Sentiment must use the declared enum."))
        if "confidence" in df:
            confidence = pd.to_numeric(df["confidence"], errors="coerce")
            invalid = int((confidence.isna() | ~confidence.between(0, 1)).sum())
            issues.append(_issue(table_name, "confidence_range", "blocking" if invalid else "ok", invalid, "Confidence must be within [0, 1]."))

    return pd.DataFrame(issues)


def _audit_daily_bar(df: pd.DataFrame, table_name: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    price_cols = [c for c in ["open", "high", "low", "close", "adj_factor"] if c in df.columns]
    for col in price_cols:
        invalid = int((pd.to_numeric(df[col], errors="coerce") <= 0).sum())
        if invalid:
            issues.append(_issue(table_name, f"non_positive:{col}", "blocking", invalid, "Price/factor must be positive."))
    if {"high", "low", "open", "close"}.issubset(df.columns):
        invalid_bounds = (
            (df["high"] < df["low"])
            | (df["open"] > df["high"])
            | (df["open"] < df["low"])
            | (df["close"] > df["high"])
            | (df["close"] < df["low"])
        )
        ohlc_invalid = int(invalid_bounds.sum())
        if ohlc_invalid:
            issues.append(
                _issue(table_name, "invalid_ohlc_bounds", "blocking", ohlc_invalid, "OHLC violates high/low bounds.")
            )
    for col in ["volume", "amount"]:
        if col in df.columns:
            invalid = int((pd.to_numeric(df[col], errors="coerce") < 0).sum())
            if invalid:
                issues.append(_issue(table_name, f"negative:{col}", "blocking", invalid, "Volume/amount cannot be negative."))
    if "amount" in df.columns:
        amount = pd.to_numeric(df["amount"], errors="coerce")
        zero_amount = int(amount.eq(0).sum())
        if zero_amount:
            issues.append(_issue(table_name, "zero_amount", "warning", zero_amount, "Zero turnover requires suspension/stale-price review."))
        if {"ts_code", "trade_date"}.issubset(df.columns):
            ordered = df.assign(_amount=amount).sort_values(["ts_code", "trade_date"])
            ratio = ordered.groupby("ts_code")["_amount"].pct_change().abs()
            spikes = int(ratio.gt(20).sum())
            if spikes:
                issues.append(_issue(table_name, "amount_spikes", "warning", spikes, "Absolute day-on-day amount change exceeds 2000%."))
    if {"ts_code", "trade_date", "adj_factor"}.issubset(df.columns):
        ordered = df.sort_values(["ts_code", "trade_date"])
        jumps = ordered.groupby("ts_code")["adj_factor"].pct_change().abs()
        jump_count = int(jumps.gt(0.5).sum())
        if jump_count:
            issues.append(_issue(table_name, "adj_factor_jumps", "warning", jump_count, "Adjustment-factor jump exceeds 50%; verify corporate actions."))
    return issues


def _audit_financial_point_in_time(df: pd.DataFrame, table_name: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    if {"ann_date", "usable_date"}.issubset(df.columns):
        ann = pd.to_datetime(df["ann_date"], errors="coerce")
        usable = pd.to_datetime(df["usable_date"], errors="coerce")
        leakage = int((usable.notna() & ann.notna() & (usable <= ann)).sum())
        if leakage:
            issues.append(
                _issue(
                    table_name,
                    "usable_date_not_after_ann_date",
                    "blocking",
                    leakage,
                    "usable_date must be after ann_date, normally next trading day.",
                )
            )
    return issues


def _audit_benchmark(df: pd.DataFrame, table_name: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    if "close" in df.columns:
        invalid = int((pd.to_numeric(df["close"], errors="coerce") <= 0).sum())
        if invalid:
            issues.append(_issue(table_name, "non_positive:close", "blocking", invalid, "Index close must be positive."))
    return issues


def audit_tables(
    tables: dict[str, pd.DataFrame],
    expected_tables: set[str] | None = None,
) -> pd.DataFrame:
    reports = [audit_table(df, name) for name, df in tables.items()]
    issues = pd.concat(reports, ignore_index=True) if reports else pd.DataFrame()
    if expected_tables:
        missing = sorted(expected_tables - set(tables))
        missing_rows = [
            _issue(
                table,
                "missing_table",
                "warning" if table == "news_event" else "blocking",
                table,
                "Expected standardized table is not present.",
            )
            for table in missing
        ]
        if missing_rows:
            issues = pd.concat([issues, pd.DataFrame(missing_rows)], ignore_index=True)
    cross = _audit_cross_table_consistency(tables)
    if cross:
        issues = pd.concat([issues, pd.DataFrame(cross)], ignore_index=True)
    return issues


def _overlapping_intervals(
    df: pd.DataFrame,
    group_cols: list[str],
    start_col: str,
    end_col: str,
) -> int:
    if df.empty or not set([*group_cols, start_col, end_col]).issubset(df.columns):
        return 0
    count = 0
    data = df.copy()
    data[start_col] = pd.to_datetime(data[start_col])
    data[end_col] = pd.to_datetime(data[end_col])
    for _, part in data.sort_values([*group_cols, start_col]).groupby(group_cols, dropna=False):
        previous_end: pd.Timestamp | None = None
        for row in part.itertuples(index=False):
            start = getattr(row, start_col)
            end = getattr(row, end_col)
            effective_end = pd.Timestamp.max if pd.isna(end) else pd.Timestamp(end)
            if previous_end is not None and start < previous_end:
                count += 1
            if previous_end is None or effective_end > previous_end:
                previous_end = effective_end
    return count


def _audit_cross_table_consistency(tables: dict[str, pd.DataFrame]) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    daily = tables.get("daily_bar")
    calendar = tables.get("trade_calendar")
    if daily is not None and not daily.empty:
        dates = pd.to_datetime(daily["trade_date"])
        coverage = daily.groupby(dates)["ts_code"].nunique()
        issues.append(_issue("daily_bar", "daily_asset_coverage_min", "info", int(coverage.min()), "Minimum stocks observed on a trading date."))
        if calendar is not None and not calendar.empty:
            cal = calendar.copy()
            if "is_open" in cal:
                cal = cal[cal["is_open"].astype(bool)]
            open_dates = set(pd.to_datetime(cal["trade_date"]))
            outside = int((~dates.isin(open_dates)).sum())
            issues.append(_issue("daily_bar", "dates_outside_trade_calendar", "blocking" if outside else "ok", outside, "Daily bars must fall on open trading days."))
        for name in ["daily_basic", "industry", "limit_price"]:
            other = tables.get(name)
            if other is None or other.empty or "trade_date" not in other:
                continue
            daily_keys = pd.MultiIndex.from_frame(daily[["trade_date", "ts_code"]].assign(trade_date=lambda x: pd.to_datetime(x["trade_date"])))
            other_keys = pd.MultiIndex.from_frame(other[["trade_date", "ts_code"]].assign(trade_date=lambda x: pd.to_datetime(x["trade_date"])))
            missing_rate = float((~daily_keys.isin(other_keys)).mean()) if len(daily_keys) else 0.0
            severity = "blocking" if name in {"daily_basic", "industry"} and missing_rate > 0.2 else ("warning" if missing_rate else "ok")
            issues.append(_issue(name, "daily_bar_key_missing_rate", severity, round(missing_rate, 6), "Share of daily-bar asset-date keys missing from this table."))
    industry = tables.get("industry")
    if industry is not None and "industry_code" in industry:
        missing = float(industry["industry_code"].isna().mean()) if len(industry) else 0.0
        issues.append(_issue("industry", "industry_code_missing_rate", "blocking" if missing > 0.2 else ("warning" if missing else "ok"), round(missing, 6), "Industry coverage at signal time."))
    financial = tables.get("financial_indicator")
    if financial is not None and not financial.empty and calendar is not None and not calendar.empty:
        open_calendar = calendar.copy()
        if "is_open" in open_calendar:
            open_calendar = open_calendar[open_calendar["is_open"].astype(bool)]
        open_dates = set(pd.to_datetime(open_calendar["trade_date"]))
        usable = pd.to_datetime(financial["usable_date"], errors="coerce")
        outside = int((usable.notna() & ~usable.isin(open_dates)).sum())
        issues.append(_issue(
            "financial_indicator",
            "usable_date_outside_trade_calendar",
            "blocking" if outside else "ok",
            outside,
            "Financial usable_date must be an open exchange trading date.",
        ))
    intervals = [
        ("index_member", ["index_code", "ts_code"], "in_date", "out_date"),
        ("st_status", ["ts_code"], "start_date", "end_date"),
        ("suspension", ["ts_code"], "suspend_date", "resume_date"),
    ]
    for table, groups, start, end in intervals:
        frame = tables.get(table)
        if frame is None:
            continue
        overlap = _overlapping_intervals(frame, groups, start, end)
        issues.append(_issue(table, "overlapping_intervals", "blocking" if overlap else "ok", overlap, "Intervals for the same entity must not overlap."))
    return issues


def has_blocking_issues(issues: pd.DataFrame) -> bool:
    return not issues.empty and bool(issues["severity"].eq("blocking").any())


def write_data_quality_report(
    tables: dict[str, pd.DataFrame],
    output_dir: str | Path = "reports",
    markdown_name: str = "data_quality_report.md",
    csv_name: str = "data_quality_issues.csv",
    expected_tables: set[str] | None = None,
) -> tuple[Path, Path, pd.DataFrame]:
    out_dir = ensure_dir(output_dir)
    issues = audit_tables(tables, expected_tables=expected_tables)
    csv_path = out_dir / csv_name
    md_path = out_dir / markdown_name
    issues.to_csv(csv_path, index=False, encoding="utf-8")

    blocking = issues[issues["severity"].eq("blocking")] if not issues.empty else pd.DataFrame()
    warnings = issues[issues["severity"].eq("warning")] if not issues.empty else pd.DataFrame()
    lines = [
        "# Data Quality Report",
        "",
        f"- Tables audited: {len(tables)}",
        f"- Blocking issues: {len(blocking)}",
        f"- Warnings: {len(warnings)}",
        "",
        "## Blocking Issues",
        "",
    ]
    lines.extend(_format_issue_lines(blocking))
    lines.extend(["", "## Warnings", ""])
    lines.extend(_format_issue_lines(warnings))
    lines.extend(["", f"CSV detail: `{csv_path.name}`", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, csv_path, issues


def _format_issue_lines(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return ["- None"]
    return [f"- `{row.table}` `{row.check}`: {row.value} ({row.detail})" for row in df.itertuples(index=False)]
