from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ashare_factor_research.data.pit_audit import (
    AUDIT_FILENAMES,
    REQUIRED_REAL_TABLES,
    audit_benchmark_alignment,
    audit_financial_revisions,
    audit_pit_timing,
    audit_survivorship,
    audit_universe_coverage,
)
from ashare_factor_research.data.source_registry import (
    load_source_registry,
    source_registry_sha256,
    validate_source_registry,
)
from ashare_factor_research.data.trading_calendar import (
    month_end_rebalance_dates,
    next_trade_date,
)
from ashare_factor_research.utils.io import ensure_dir


REQUIRED_COVERAGE_FIELDS = {
    "daily_bar": ["amount", "adj_factor"],
}


def attach_monthly_label_returns(
    factor_panel: pd.DataFrame,
    daily_bar: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    return_col: str = "monthly_forward_return",
) -> pd.DataFrame:
    """Attach next-open to adjacent-month-end returns to signal-date factors."""

    required_panel = {"trade_date", "ts_code"}
    required_bar = {"trade_date", "ts_code", "open", "close", "adj_factor"}
    required_labels = {"signal_date", "execution_date", "label_end_date", "availability_date"}
    for name, missing in {
        "factor_panel": required_panel - set(factor_panel),
        "daily_bar": required_bar - set(daily_bar),
        "labels": required_labels - set(labels),
    }.items():
        if missing:
            raise ValueError(f"{name} missing monthly-label fields: {sorted(missing)}")

    label_frame = labels[list(required_labels)].copy()
    for column in required_labels:
        label_frame[column] = pd.to_datetime(label_frame[column], errors="coerce")
    if label_frame.isna().any(axis=None):
        raise ValueError("monthly labels contain invalid dates")
    if label_frame["signal_date"].duplicated().any():
        raise ValueError("monthly labels contain duplicate signal_date")

    panel = factor_panel.copy()
    panel["trade_date"] = pd.to_datetime(panel["trade_date"])
    panel["ts_code"] = panel["ts_code"].astype(str)
    panel = panel[panel["trade_date"].isin(label_frame["signal_date"])].copy()
    panel = panel.drop(
        columns=["execution_date", "label_end_date", "availability_date", "target_return_end_date", return_col],
        errors="ignore",
    )
    panel = panel.merge(label_frame, left_on="trade_date", right_on="signal_date", how="inner", validate="many_to_one")

    bars = daily_bar[list(required_bar)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars["ts_code"] = bars["ts_code"].astype(str)
    if bars.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("daily_bar has duplicate (trade_date, ts_code) keys")
    bars["adjusted_open"] = pd.to_numeric(bars["open"], errors="coerce") * pd.to_numeric(bars["adj_factor"], errors="coerce")
    bars["adjusted_close"] = pd.to_numeric(bars["close"], errors="coerce") * pd.to_numeric(bars["adj_factor"], errors="coerce")
    execution_prices = bars[["trade_date", "ts_code", "adjusted_open"]].rename(columns={"trade_date": "execution_date"})
    end_prices = bars[["trade_date", "ts_code", "adjusted_close"]].rename(columns={"trade_date": "label_end_date"})
    panel = panel.merge(execution_prices, on=["execution_date", "ts_code"], how="left", validate="many_to_one")
    panel = panel.merge(end_prices, on=["label_end_date", "ts_code"], how="left", validate="many_to_one")
    valid_open = panel["adjusted_open"].where(panel["adjusted_open"].gt(0.0))
    panel[return_col] = panel["adjusted_close"] / valid_open - 1.0
    panel["target_return_end_date"] = panel["label_end_date"]
    return panel.drop(columns=["adjusted_open", "adjusted_close"])


def build_monthly_labels(
    trade_dates: pd.DatetimeIndex | list[str] | list[pd.Timestamp],
    *,
    horizon: int = 1,
    final_holdout_start: str = "2024-01-01",
) -> pd.DataFrame:
    """Build strictly point-in-time monthly labels.

    signal_date = month-end close
    execution_date = next trading-day open
    label_end_date = the month-end ``horizon`` months after signal_date
    availability_date = first trading day strictly after label_end_date

    Labels must not overlap (label_end_date < next_signal_date) and must not
    cross into the final holdout period.
    """

    dates = pd.DatetimeIndex(pd.to_datetime(trade_dates)).sort_values().unique()
    if horizon < 1:
        raise ValueError("horizon must be at least one month")
    if horizon != 1:
        raise ValueError(
            "Monthly labels would overlap: phase 2 only permits adjacent one-month intervals"
        )
    if len(dates) < 3:
        raise ValueError("Need at least three trade dates to build monthly labels")
    holdout = pd.Timestamp(final_holdout_start)
    month_ends = month_end_rebalance_dates(dates)
    rows: list[dict[str, object]] = []
    for month_pos, signal_date in enumerate(month_ends):
        if pd.Timestamp(signal_date) >= holdout:
            continue
        end_pos = month_pos + horizon
        if end_pos >= len(month_ends):
            continue
        execution_date = next_trade_date(dates, pd.Timestamp(signal_date))
        if execution_date is None:
            continue
        label_end_date = pd.Timestamp(month_ends[end_pos])
        availability_date = next_trade_date(dates, pd.Timestamp(label_end_date))
        if availability_date is None:
            continue
        if label_end_date >= holdout or pd.Timestamp(availability_date) >= holdout:
            raise ValueError(
                "Monthly label crosses final holdout: "
                f"signal={pd.Timestamp(signal_date).date()}, "
                f"label_end={label_end_date.date()}, "
                f"availability={pd.Timestamp(availability_date).date()}, "
                f"holdout={holdout.date()}"
            )
        rows.append({
            "signal_date": pd.Timestamp(signal_date),
            "execution_date": pd.Timestamp(execution_date),
            "label_end_date": pd.Timestamp(label_end_date),
            "availability_date": pd.Timestamp(availability_date),
        })
    if not rows:
        raise ValueError("No valid monthly labels could be constructed")
    labels = pd.DataFrame(rows).sort_values("signal_date").reset_index(drop=True)
    next_signal = labels["signal_date"].shift(-1)
    # Adjacent one-month intervals share the month-end boundary but their
    # executable holding periods do not overlap: the next period starts at the
    # following session's open.  A label ending after the next signal overlaps.
    overlap = labels["label_end_date"].gt(next_signal) & next_signal.notna()
    if overlap.any():
        sample = labels.loc[overlap, ["signal_date", "label_end_date"]].head(3).to_dict("records")
        raise ValueError(f"Monthly labels overlap with the next signal date: {sample}")
    holdout_cross = labels[["signal_date", "execution_date", "label_end_date", "availability_date"]].ge(holdout).any(axis=1)
    if holdout_cross.any():
        sample = labels.loc[holdout_cross, ["signal_date", "label_end_date"]].head(3).to_dict("records")
        raise ValueError(f"Labels cross into final holdout starting {holdout.date()}: {sample}")
    return labels


def _require_manifest_real(source_manifest: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    if source_manifest is None:
        reasons.append("missing real data_manifest.json")
        return reasons
    if source_manifest.get("mode") != "real":
        reasons.append("data manifest mode is not real")
    if source_manifest.get("_verification_error"):
        reasons.append(f"manifest verification failed: {source_manifest['_verification_error']}")
    if source_manifest.get("import_gate_status") != "ready_for_quality_audit":
        reasons.append("import manifest is not ready_for_quality_audit")
    return reasons


def _require_registry_signoff(source_manifest: dict[str, Any] | None) -> list[str]:
    """Return blocking reasons if the registry has not been explicitly signed.

    Does not modify the registry or any manifest field.
    """

    if source_manifest is None:
        return []
    reasons: list[str] = []
    registry = source_manifest.get("source_registry_validation", {})
    if not registry.get("valid", False):
        return reasons
    if source_manifest.get("review_status") != "approved":
        reasons.append("source registry review_status is not approved")
    if not str(source_manifest.get("reviewed_by") or "").strip():
        reasons.append("source registry reviewed_by is missing")
    if not str(source_manifest.get("reviewed_at") or "").strip():
        reasons.append("source registry reviewed_at is missing")
    return reasons


def _require_source_registry_validation(
    source_manifest: dict[str, Any] | None,
    data_dir: Path,
    required_tables: set[str],
) -> list[str]:
    reasons: list[str] = []
    if source_manifest is None:
        return reasons
    validation = source_manifest.get("source_registry_validation", {})
    if not validation.get("valid", False):
        errors = validation.get("errors", ["source registry not approved"])
        reasons.extend(str(item) for item in errors)
    if not source_manifest.get("source_registry_sha256"):
        reasons.append("source registry hash is missing")
    registry_path = source_manifest.get("source_registry_path")
    if registry_path and Path(registry_path).exists():
        try:
            registry = load_source_registry(registry_path)
            current_hash = source_registry_sha256(registry)
            if current_hash != source_manifest.get("source_registry_sha256"):
                reasons.append("current source registry hash does not match manifest")
            validated = validate_source_registry(registry, required_tables)
            reasons.extend(str(item) for item in validated.errors)
        except Exception as exc:
            reasons.append(f"source registry validation error: {exc}")
    elif registry_path:
        reasons.append(f"source registry path does not exist: {registry_path}")
    return reasons


def check_real_mode_gates(
    data: dict[str, pd.DataFrame],
    source_manifest: dict[str, Any] | None,
    *,
    required_tables: set[str] | None = None,
    audits: dict[str, pd.DataFrame] | None = None,
    min_coverage: float = 0.95,
    required_fields: dict[str, list[str]] | None = None,
    required_start: str = "2015-01-01",
    final_holdout_start: str = "2024-01-01",
    labels: pd.DataFrame | None = None,
    data_dir: Path | None = None,
) -> list[str]:
    """Return blocking reasons for real-mode monthly-sample build.

    Implements the six hard gates:
      1. verified real manifest/source registry
      2. explicit global signoff
      3. all required PIT tables
      4. nonempty specialized audits with no failed rows
      5. historical-member coverage >= min_coverage for amount, adj_factor, factor fields
      6. strict timeline/holdout rules
    """

    required_tables = set(required_tables or REQUIRED_REAL_TABLES)
    required_fields = dict(required_fields or REQUIRED_COVERAGE_FIELDS)
    blocking: list[str] = []

    blocking.extend(_require_manifest_real(source_manifest))
    if source_manifest is not None and data_dir is not None:
        blocking.extend(_require_source_registry_validation(source_manifest, data_dir, required_tables))
    blocking.extend(_require_registry_signoff(source_manifest))

    missing_tables = sorted(required_tables - set(data))
    if missing_tables:
        blocking.append(f"missing required tables: {missing_tables}")
    for table in required_tables & set(data):
        if data[table].empty:
            blocking.append(f"required table is empty: {table}")

    if audits is None:
        blocking.append("missing specialized audit bundle")
    else:
        for name in AUDIT_FILENAMES:
            if name not in audits:
                blocking.append(f"missing specialized audit: {name}")
                continue
            frame = audits[name]
            if frame.empty:
                blocking.append(f"audit {name}: no auditable rows")
                continue
            if "passed" in frame and not frame["passed"].fillna(False).astype(bool).all():
                failed = frame.loc[~frame["passed"].fillna(False), :].head(3).to_dict("records")
                blocking.append(f"audit {name}: failed rows {failed}")

    calendar = data.get("trade_calendar")
    daily_bar = data.get("daily_bar")
    allowed_first_date = pd.Timestamp(required_start) + pd.Timedelta(days=7)
    if calendar is None or calendar.empty or pd.to_datetime(calendar["trade_date"]).min() > allowed_first_date:
        blocking.append(f"trade calendar does not cover the start of {required_start}")
    if daily_bar is None or daily_bar.empty or pd.to_datetime(daily_bar["trade_date"]).min() > allowed_first_date:
        blocking.append(f"daily bars do not cover the start of {required_start}")

    coverage = compute_historical_member_coverage(
        data,
        required_fields=required_fields,
        required_start=required_start,
    )
    if coverage.empty:
        blocking.append("historical-member coverage has no auditable rows")
    else:
        low = coverage[coverage["coverage"] < min_coverage]
        if not low.empty:
            sample = low.head(3).to_dict("records")
            blocking.append(f"historical-member coverage below {min_coverage}: {sample}")

    if labels is not None and labels.empty:
        blocking.append("monthly labels are empty")
    if labels is not None and not labels.empty:
        required_label_columns = {"signal_date", "execution_date", "label_end_date", "availability_date"}
        missing_label_columns = sorted(required_label_columns - set(labels.columns))
        if missing_label_columns:
            blocking.append(f"monthly labels missing timing columns: {missing_label_columns}")
            return blocking
        labels = labels.copy()
        for column in required_label_columns:
            labels[column] = pd.to_datetime(labels[column], errors="coerce")
        if labels[list(required_label_columns)].isna().any(axis=None):
            blocking.append("monthly labels contain invalid timing values")
        holdout = pd.Timestamp(final_holdout_start)
        holdout_mask = labels[["signal_date", "execution_date", "label_end_date", "availability_date"]].ge(holdout).any(axis=1)
        if holdout_mask.any():
            sample = labels.loc[holdout_mask, ["signal_date", "execution_date", "label_end_date", "availability_date"]].head(3).to_dict("records")
            blocking.append(f"labels cross into final holdout starting {holdout.date()}: {sample}")
        invalid_order = ~(
            labels["signal_date"].lt(labels["execution_date"])
            & labels["execution_date"].le(labels["label_end_date"])
            & labels["label_end_date"].lt(labels["availability_date"])
        )
        if invalid_order.any():
            sample = labels.loc[invalid_order, list(required_label_columns)].head(3).to_dict("records")
            blocking.append(f"invalid monthly label timing order: {sample}")
        next_signal = labels["signal_date"].shift(-1)
        overlap = labels["label_end_date"].gt(next_signal) & next_signal.notna()
        if overlap.any():
            sample = labels.loc[overlap, ["signal_date", "label_end_date"]].head(3).to_dict("records")
            blocking.append(f"overlapping monthly labels: {sample}")

    return blocking


def compute_historical_member_coverage(
    tables: dict[str, pd.DataFrame],
    *,
    index_code: str = "000905.SH",
    required_fields: dict[str, list[str]] | None = None,
    required_start: str = "2015-01-01",
) -> pd.DataFrame:
    """Compute per-date coverage of required fields over active historical members."""

    required_fields = dict(required_fields or REQUIRED_COVERAGE_FIELDS)
    members = tables.get("index_member")
    calendar = tables.get("trade_calendar")
    if members is None or members.empty or calendar is None or calendar.empty:
        return pd.DataFrame(columns=["trade_date", "table", "field", "active_count", "non_missing_count", "coverage"])

    cal = calendar.copy()
    if "is_open" in cal:
        cal = cal[cal["is_open"].astype(bool)]
    dates = pd.DatetimeIndex(pd.to_datetime(cal["trade_date"]).dropna().unique()).sort_values()
    dates = dates[dates >= pd.Timestamp(required_start)]

    member = members[members["index_code"].astype(str).eq(index_code)].copy()
    member["in_date"] = pd.to_datetime(member["in_date"], errors="coerce")
    member["out_date"] = pd.to_datetime(member["out_date"], errors="coerce")

    rows: list[dict[str, object]] = []
    for date in dates:
        active_mask = member["in_date"].le(date) & (member["out_date"].isna() | member["out_date"].gt(date))
        active = set(member.loc[active_mask, "ts_code"].astype(str))
        active_count = len(active)
        if active_count == 0:
            continue
        for table_name, fields in required_fields.items():
            table = tables.get(table_name)
            if table is None or table.empty:
                for field in fields:
                    rows.append({
                        "trade_date": date,
                        "table": table_name,
                        "field": field,
                        "active_count": active_count,
                        "non_missing_count": 0,
                        "coverage": 0.0,
                    })
                continue
            day = table[pd.to_datetime(table["trade_date"]).eq(date)].copy()
            day["ts_code"] = day["ts_code"].astype(str)
            for field in fields:
                if field not in day:
                    non_missing = 0
                else:
                    non_missing = int(day[day["ts_code"].isin(active)][field].notna().sum())
                rows.append({
                    "trade_date": date,
                    "table": table_name,
                    "field": field,
                    "active_count": active_count,
                    "non_missing_count": non_missing,
                    "coverage": non_missing / active_count,
                })
    return pd.DataFrame(rows)


def build_real_mode_audits(
    tables: dict[str, pd.DataFrame],
    *,
    index_code: str = "000905.SH",
    required_start: str = "2015-01-01",
    min_coverage: float = 0.95,
) -> dict[str, pd.DataFrame]:
    """Run the same specialized audits used by the real data gate."""

    return {
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


def write_monthly_artifacts(
    output_dir: str | Path,
    monthly_ic: pd.DataFrame,
    monthly_returns: pd.DataFrame,
    state_variables: pd.DataFrame,
) -> dict[str, Path]:
    """Persist the three core monthly artifacts."""

    out = ensure_dir(output_dir)
    paths = {
        "monthly_factor_ic": out / "monthly_factor_ic.csv",
        "monthly_factor_returns": out / "monthly_factor_returns.csv",
        "monthly_state_variables": out / "monthly_state_variables.csv",
    }
    monthly_ic.to_csv(paths["monthly_factor_ic"], index=False, encoding="utf-8")
    monthly_returns.to_csv(paths["monthly_factor_returns"], index=False, encoding="utf-8")
    state_variables.to_csv(paths["monthly_state_variables"], index=False, encoding="utf-8")
    return paths


def load_or_build_manifest(data_dir: str | Path) -> dict[str, Any] | None:
    """Load data_manifest.json if it exists, otherwise return None."""

    path = Path(data_dir) / "data_manifest.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None
