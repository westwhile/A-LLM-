"""PIT-safe event-to-company-date aggregation for R1 representations."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ashare_factor_research.data.provenance import dataframe_sha256
from ashare_factor_research.llm.representation import validate_text_representation_rows
from ashare_factor_research.utils.helpers import require_columns


TEXT_AGGREGATION_VERSION = "r1_text_aggregation_v1"


def aggregate_text_representation(
    rows: pd.DataFrame,
    signal_schedule: pd.DataFrame,
    *,
    feature_cols: list[str],
    lookback_days: int = 20,
    decay_half_life_days: float | None = None,
    feature_prefix: str = "text_",
) -> pd.DataFrame:
    """Aggregate only information available at each explicit signal cutoff.

    The result contains rows only when signal-ready text exists.  Callers must
    decide and preregister how missing company-date rows are represented; this
    function never silently turns missing coverage into neutral sentiment.
    """

    validate_text_representation_rows(rows)
    require_columns(signal_schedule, ["signal_date", "signal_cutoff"], "signal_schedule")
    require_columns(rows, feature_cols, "text_representation")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if decay_half_life_days is not None and decay_half_life_days <= 0:
        raise ValueError("decay_half_life_days must be positive")
    if not feature_cols:
        raise ValueError("feature_cols must be non-empty")
    if len(set(feature_cols)) != len(feature_cols):
        raise ValueError("feature_cols must be unique")
    events = rows.copy()
    events["available_time"] = pd.to_datetime(events["available_time"], errors="coerce")
    numeric = events[feature_cols].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        invalid = numeric.columns[numeric.isna().any()].tolist()
        raise ValueError(f"text aggregation features must be complete and numeric: {invalid}")
    events[feature_cols] = numeric
    events = events[events["entity_mapping_status"].isin(["matched", "reviewed_matched"])].copy()

    schedule = signal_schedule.copy()
    schedule["signal_date"] = pd.to_datetime(schedule["signal_date"], errors="coerce")
    schedule["signal_cutoff"] = pd.to_datetime(schedule["signal_cutoff"], errors="coerce")
    if schedule[["signal_date", "signal_cutoff"]].isna().any().any():
        raise ValueError("signal schedule dates must be parseable")
    if schedule["signal_date"].duplicated().any():
        raise ValueError("signal schedule must be unique by signal_date")

    output: list[pd.DataFrame] = []
    for schedule_row in schedule.sort_values("signal_date").to_dict("records"):
        cutoff = pd.Timestamp(schedule_row["signal_cutoff"])
        start = cutoff - pd.Timedelta(days=lookback_days)
        window = events[events["available_time"].between(start, cutoff, inclusive="both")].copy()
        if window.empty:
            continue
        window = window.sort_values(["available_time", "event_id"], kind="mergesort").drop_duplicates(
            ["stock_code", "dedup_group_id"],
            keep="first",
        )
        age_days = (cutoff - window["available_time"]).dt.total_seconds() / 86400.0
        if decay_half_life_days is None:
            window["_weight"] = 1.0
        else:
            window["_weight"] = np.power(0.5, age_days / float(decay_half_life_days))
        parts: list[dict[str, object]] = []
        for stock_code, stock_rows in window.groupby("stock_code", sort=True):
            weights = stock_rows["_weight"].to_numpy(dtype=float)
            item: dict[str, object] = {
                "signal_date": pd.Timestamp(schedule_row["signal_date"]),
                "signal_cutoff": cutoff,
                "ts_code": str(stock_code),
                "text_coverage": 1.0,
                "text_event_count": int(len(stock_rows)),
                "text_latest_available_time": stock_rows["available_time"].max(),
            }
            for feature in feature_cols:
                values = stock_rows[feature].to_numpy(dtype=float)
                item[f"{feature_prefix}{feature}"] = float(np.average(values, weights=weights))
            parts.append(item)
        output.append(pd.DataFrame(parts))
    if not output:
        return pd.DataFrame(
            columns=[
                "signal_date",
                "signal_cutoff",
                "ts_code",
                "text_coverage",
                "text_event_count",
                "text_latest_available_time",
                *[f"{feature_prefix}{feature}" for feature in feature_cols],
            ]
        )
    result = pd.concat(output, ignore_index=True)
    if (pd.to_datetime(result["text_latest_available_time"]) > pd.to_datetime(result["signal_cutoff"])).any():
        raise ValueError("text aggregation emitted a future event")
    return result.sort_values(["signal_date", "ts_code"], kind="mergesort").reset_index(drop=True)


def build_text_feature_artifact(
    features: pd.DataFrame,
    *,
    representation_manifest_sha256: str,
    feature_cols: list[str],
    lookback_days: int,
    decay_half_life_days: float | None,
) -> dict[str, Any]:
    if len(representation_manifest_sha256) != 64:
        raise ValueError("representation_manifest_sha256 must be a SHA-256 digest")
    require_columns(features, ["signal_date", "signal_cutoff", "ts_code", "text_coverage"], "text_features")
    configuration = {
        "aggregation_version": TEXT_AGGREGATION_VERSION,
        "representation_manifest_sha256": representation_manifest_sha256,
        "feature_cols": list(feature_cols),
        "lookback_days": int(lookback_days),
        "decay_half_life_days": decay_half_life_days,
        "missingness_rule": "absent company-date row means no signal-ready text; no implicit neutral fill",
    }
    digest = hashlib.sha256(
        json.dumps(configuration, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "artifact_type": "r1_text_feature_set",
        "schema_version": 1,
        "status": "draft",
        "configuration": configuration,
        "configuration_sha256": digest,
        "rows": int(len(features)),
        "features_sha256": dataframe_sha256(features),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def write_text_feature_artifact(
    features: pd.DataFrame,
    output_dir: str | Path,
    **manifest_kwargs: Any,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    artifact = build_text_feature_artifact(features, **manifest_kwargs)
    features.to_csv(root / "text_features.csv", index=False, encoding="utf-8")
    (root / "text_feature_manifest.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return artifact
