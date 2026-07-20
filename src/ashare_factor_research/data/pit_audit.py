from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ashare_factor_research.data.data_quality import REAL_DATA_EXPECTED_TABLES, has_blocking_issues
from ashare_factor_research.utils.io import ensure_dir


REQUIRED_REAL_TABLES = REAL_DATA_EXPECTED_TABLES - {"news_event"}
AUDIT_FILENAMES = (
    "pit_timing_audit.csv",
    "financial_revision_audit.csv",
    "survivorship_audit.csv",
    "universe_coverage.csv",
    "benchmark_alignment.csv",
)


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def audit_pit_timing(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    columns = [
        "table", "ts_code", "report_period", "announcement_date", "revision_date",
        "usable_date", "source_id", "passed", "issue",
    ]
    financial = tables.get("financial_indicator")
    required = {"ts_code", "report_period", "ann_date", "usable_date", "revision_date", "revision_id", "source_id"}
    if financial is None or financial.empty:
        return _empty(columns)
    missing = sorted(required - set(financial.columns))
    if missing:
        return pd.DataFrame([{
            "table": "financial_indicator", "passed": False,
            "issue": f"missing real-PIT fields: {missing}",
        }], columns=columns)

    frame = financial.copy()
    for column in ["report_period", "ann_date", "revision_date", "usable_date"]:
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    info_date = frame[["ann_date", "revision_date"]].max(axis=1)
    valid = (
        frame["report_period"].notna()
        & frame["ann_date"].notna()
        & frame["revision_date"].notna()
        & frame["usable_date"].notna()
        & frame["source_id"].astype("string").str.strip().ne("")
        & frame["report_period"].le(frame["ann_date"])
        & frame["revision_date"].ge(frame["ann_date"])
        & frame["usable_date"].gt(info_date)
    )
    issues = []
    for idx in frame.index:
        row_issues: list[str] = []
        if pd.isna(frame.at[idx, "report_period"]) or frame.at[idx, "report_period"] > frame.at[idx, "ann_date"]:
            row_issues.append("report_period_after_announcement")
        if pd.isna(frame.at[idx, "revision_date"]) or frame.at[idx, "revision_date"] < frame.at[idx, "ann_date"]:
            row_issues.append("revision_before_announcement")
        if pd.isna(frame.at[idx, "usable_date"]) or frame.at[idx, "usable_date"] <= info_date.at[idx]:
            row_issues.append("usable_date_not_after_latest_information")
        if not str(frame.at[idx, "source_id"]).strip():
            row_issues.append("source_id_missing")
        issues.append(";".join(row_issues))
    return pd.DataFrame({
        "table": "financial_indicator",
        "ts_code": frame["ts_code"],
        "report_period": frame["report_period"],
        "announcement_date": frame["ann_date"],
        "revision_date": frame["revision_date"],
        "usable_date": frame["usable_date"],
        "source_id": frame["source_id"],
        "passed": valid.astype(bool),
        "issue": issues,
    }, columns=columns)


def audit_financial_revisions(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    columns = [
        "ts_code", "report_period", "revision_count", "first_announcement_date",
        "last_revision_date", "revision_ids_unique", "passed", "issue",
    ]
    financial = tables.get("financial_indicator")
    required = {"ts_code", "report_period", "ann_date", "revision_date", "revision_id"}
    if financial is None or financial.empty:
        return _empty(columns)
    missing = sorted(required - set(financial.columns))
    if missing:
        return pd.DataFrame([{"passed": False, "issue": f"missing revision fields: {missing}"}], columns=columns)
    frame = financial.copy()
    frame["report_period"] = pd.to_datetime(frame["report_period"], errors="coerce")
    frame["ann_date"] = pd.to_datetime(frame["ann_date"], errors="coerce")
    frame["revision_date"] = pd.to_datetime(frame["revision_date"], errors="coerce")
    rows = []
    for (code, period), part in frame.groupby(["ts_code", "report_period"], dropna=False):
        ids_unique = not part["revision_id"].duplicated().any()
        dates_valid = bool((part["revision_date"] >= part["ann_date"]).fillna(False).all())
        passed = ids_unique and dates_valid
        issues = []
        if not ids_unique:
            issues.append("duplicate_revision_id")
        if not dates_valid:
            issues.append("invalid_revision_date")
        rows.append({
            "ts_code": code,
            "report_period": period,
            "revision_count": int(len(part)),
            "first_announcement_date": part["ann_date"].min(),
            "last_revision_date": part["revision_date"].max(),
            "revision_ids_unique": ids_unique,
            "passed": passed,
            "issue": ";".join(issues),
        })
    return pd.DataFrame(rows, columns=columns)


def audit_survivorship(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    columns = [
        "ts_code", "list_date", "delist_date", "has_security_master",
        "has_index_membership", "has_daily_bar", "passed", "issue",
    ]
    basic = tables.get("stock_basic")
    members = tables.get("index_member")
    bars = tables.get("daily_bar")
    if basic is None or members is None or bars is None:
        return _empty(columns)
    basic_codes = set(basic["ts_code"].astype(str))
    member_codes = set(members["ts_code"].astype(str))
    bar_codes = set(bars["ts_code"].astype(str))
    lookup = basic.set_index(basic["ts_code"].astype(str), drop=False)
    rows = []
    for code in sorted(basic_codes | member_codes):
        has_master = code in basic_codes
        has_member = code in member_codes
        has_bar = code in bar_codes
        passed = has_master and (not has_member or has_bar)
        issue = ""
        if not has_master:
            issue = "historical_member_missing_security_master"
        elif has_member and not has_bar:
            issue = "historical_member_missing_daily_bar"
        record = lookup.loc[code] if has_master else None
        if isinstance(record, pd.DataFrame):
            record = record.iloc[0]
        rows.append({
            "ts_code": code,
            "list_date": record.get("list_date") if record is not None else pd.NaT,
            "delist_date": record.get("delist_date") if record is not None else pd.NaT,
            "has_security_master": has_master,
            "has_index_membership": has_member,
            "has_daily_bar": has_bar,
            "passed": passed,
            "issue": issue,
        })
    return pd.DataFrame(rows, columns=columns)


def _keys_by_date(frame: pd.DataFrame | None) -> dict[pd.Timestamp, set[str]]:
    if frame is None or frame.empty or not {"trade_date", "ts_code"}.issubset(frame.columns):
        return {}
    data = frame[["trade_date", "ts_code"]].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    return {date: set(part["ts_code"].astype(str)) for date, part in data.groupby("trade_date")}


def audit_universe_coverage(
    tables: dict[str, pd.DataFrame],
    *,
    index_code: str = "000905.SH",
    required_start: str = "2015-01-01",
    min_coverage: float = 0.95,
) -> pd.DataFrame:
    columns = [
        "trade_date", "active_member_count", "daily_bar_coverage", "daily_basic_coverage",
        "industry_coverage", "limit_price_coverage", "minimum_coverage", "passed", "issue",
    ]
    calendar = tables.get("trade_calendar")
    members = tables.get("index_member")
    if calendar is None or members is None or calendar.empty or members.empty:
        return _empty(columns)
    cal = calendar.copy()
    if "is_open" in cal:
        cal = cal[cal["is_open"].astype(bool)]
    dates = pd.DatetimeIndex(pd.to_datetime(cal["trade_date"]).dropna().unique()).sort_values()
    dates = dates[dates >= pd.Timestamp(required_start)]
    member = members[members["index_code"].astype(str).eq(index_code)].copy()
    member["in_date"] = pd.to_datetime(member["in_date"], errors="coerce")
    member["out_date"] = pd.to_datetime(member["out_date"], errors="coerce")
    keyed = {name: _keys_by_date(tables.get(name)) for name in ["daily_bar", "daily_basic", "industry", "limit_price"]}
    rows = []
    for date in dates:
        active_mask = member["in_date"].le(date) & (member["out_date"].isna() | member["out_date"].gt(date))
        active = set(member.loc[active_mask, "ts_code"].astype(str))
        count = len(active)
        coverages = {
            name: (len(active & keyed[name].get(date, set())) / count if count else 0.0)
            for name in keyed
        }
        minimum = min(coverages.values()) if coverages else 0.0
        passed = count > 0 and minimum >= min_coverage
        rows.append({
            "trade_date": date,
            "active_member_count": count,
            "daily_bar_coverage": coverages["daily_bar"],
            "daily_basic_coverage": coverages["daily_basic"],
            "industry_coverage": coverages["industry"],
            "limit_price_coverage": coverages["limit_price"],
            "minimum_coverage": minimum,
            "passed": passed,
            "issue": "" if passed else ("no_active_historical_members" if count == 0 else "coverage_below_threshold"),
        })
    return pd.DataFrame(rows, columns=columns)


def audit_benchmark_alignment(
    tables: dict[str, pd.DataFrame],
    *,
    index_code: str = "000905.SH",
    required_start: str = "2015-01-01",
) -> pd.DataFrame:
    columns = ["trade_date", "has_open_calendar", "has_benchmark", "has_daily_bar", "passed", "issue"]
    calendar = tables.get("trade_calendar")
    benchmark = tables.get("benchmark_index")
    bars = tables.get("daily_bar")
    if calendar is None or benchmark is None or bars is None:
        return _empty(columns)
    cal = calendar.copy()
    if "is_open" in cal:
        cal = cal[cal["is_open"].astype(bool)]
    dates = pd.DatetimeIndex(pd.to_datetime(cal["trade_date"]).dropna().unique()).sort_values()
    dates = dates[dates >= pd.Timestamp(required_start)]
    benchmark_dates = set(pd.to_datetime(
        benchmark.loc[benchmark["index_code"].astype(str).eq(index_code), "trade_date"]
    ))
    bar_dates = set(pd.to_datetime(bars["trade_date"]))
    rows = []
    for date in dates:
        has_benchmark = date in benchmark_dates
        has_bar = date in bar_dates
        passed = has_benchmark and has_bar
        issue = "" if passed else ";".join([
            *( ["benchmark_missing"] if not has_benchmark else [] ),
            *( ["daily_bar_missing"] if not has_bar else [] ),
        ])
        rows.append({
            "trade_date": date,
            "has_open_calendar": True,
            "has_benchmark": has_benchmark,
            "has_daily_bar": has_bar,
            "passed": passed,
            "issue": issue,
        })
    return pd.DataFrame(rows, columns=columns)


def _require_registry_signoff(source_manifest: dict[str, Any] | None) -> list[str]:
    """Return blocking reasons if the registry has not been explicitly signed.

    The quality gate only runs after all required tables are present, so this
    is the last point where an unsigned registry must be hard-blocked.
    """
    if source_manifest is None:
        return []
    reasons: list[str] = []
    registry = source_manifest.get("source_registry_validation", {})
    if not registry.get("valid", False):
        return reasons  # validation errors are already surfaced separately
    if source_manifest.get("review_status") != "approved":
        reasons.append("source registry review_status is not approved")
    if not str(source_manifest.get("reviewed_by") or "").strip():
        reasons.append("source registry reviewed_by is missing")
    if not str(source_manifest.get("reviewed_at") or "").strip():
        reasons.append("source registry reviewed_at is missing")
    return reasons


def write_real_data_gate(
    tables: dict[str, pd.DataFrame],
    output_dir: str | Path,
    *,
    source_manifest: dict[str, Any] | None = None,
    index_code: str = "000905.SH",
    required_start: str = "2015-01-01",
    min_coverage: float = 0.95,
    quality_issues: pd.DataFrame | None = None,
) -> dict[str, Any]:
    out = ensure_dir(output_dir)
    audits = {
        "pit_timing_audit.csv": audit_pit_timing(tables),
        "financial_revision_audit.csv": audit_financial_revisions(tables),
        "survivorship_audit.csv": audit_survivorship(tables),
        "universe_coverage.csv": audit_universe_coverage(
            tables, index_code=index_code, required_start=required_start, min_coverage=min_coverage
        ),
        "benchmark_alignment.csv": audit_benchmark_alignment(
            tables, index_code=index_code, required_start=required_start
        ),
    }
    for filename, frame in audits.items():
        frame.to_csv(out / filename, index=False, encoding="utf-8")

    missing_tables = sorted(REQUIRED_REAL_TABLES - set(tables))
    blocking_reasons: list[str] = []
    if missing_tables:
        blocking_reasons.append(f"missing required tables: {missing_tables}")
    if source_manifest is None:
        blocking_reasons.append("missing real data_manifest.json")
    else:
        if source_manifest.get("mode") != "real":
            blocking_reasons.append("data manifest mode is not real")
        if source_manifest.get("_verification_error"):
            blocking_reasons.append(f"manifest verification failed: {source_manifest['_verification_error']}")
        if source_manifest.get("_protocol_binding_error"):
            blocking_reasons.append(str(source_manifest["_protocol_binding_error"]))
        if source_manifest.get("import_gate_status") != "ready_for_quality_audit":
            blocking_reasons.append("import manifest is not ready_for_quality_audit")
        validation = source_manifest.get("source_registry_validation", {})
        if not validation.get("valid", False):
            blocking_reasons.extend(str(item) for item in validation.get("errors", ["source registry not approved"]))
        if not source_manifest.get("source_registry_sha256"):
            blocking_reasons.append("source registry hash is missing")
        if not missing_tables:
            blocking_reasons.extend(_require_registry_signoff(source_manifest))
    if quality_issues is not None and has_blocking_issues(quality_issues):
        failed = quality_issues.loc[quality_issues["severity"].eq("blocking"), ["table", "check"]]
        blocking_reasons.extend(
            f"data quality failed: {row.table}.{row.check}" for row in failed.itertuples(index=False)
        )
    calendar = tables.get("trade_calendar")
    daily_bar = tables.get("daily_bar")
    allowed_first_date = pd.Timestamp(required_start) + pd.Timedelta(days=7)
    if calendar is None or calendar.empty or pd.to_datetime(calendar["trade_date"]).min() > allowed_first_date:
        blocking_reasons.append(f"trade calendar does not cover the start of {required_start}")
    if daily_bar is None or daily_bar.empty or pd.to_datetime(daily_bar["trade_date"]).min() > allowed_first_date:
        blocking_reasons.append(f"daily bars do not cover the start of {required_start}")
    for filename, frame in audits.items():
        if frame.empty:
            blocking_reasons.append(f"{filename}: no auditable rows")
        elif "passed" in frame and not frame["passed"].fillna(False).astype(bool).all():
            blocking_reasons.append(f"{filename}: failed rows present")

    status = "passed" if not blocking_reasons else (
        "blocked_by_missing_pit_tables" if missing_tables else "blocked_by_pit_quality"
    )
    summary = {
        "schema_version": 1,
        "status": status,
        "required_start": required_start,
        "benchmark": index_code,
        "minimum_coverage": min_coverage,
        "source_registry_sha256": source_manifest.get("source_registry_sha256") if source_manifest else None,
        "missing_required_tables": missing_tables,
        "blocking_reasons": blocking_reasons,
        "audit_rows": {name: int(len(frame)) for name, frame in audits.items()},
    }
    (out / "data_gate_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return summary
