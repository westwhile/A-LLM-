from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ashare_factor_research.data.data_loader import STANDARD_TABLES
from ashare_factor_research.data.data_quality import REAL_DATA_EXPECTED_TABLES
from ashare_factor_research.data.provenance import SCHEMA_VERSION, dataframe_sha256
from ashare_factor_research.data.schema import DATE_COLUMNS, normalize_table_dates, validate_schema
from ashare_factor_research.data.source_registry import (
    load_source_registry,
    sanitized_table_sources,
    validate_source_registry,
)
from ashare_factor_research.utils.io import ensure_dir, load_yaml


def _read_source(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_registry_signoff(registry: dict[str, Any] | None, present_tables: list[str]) -> None:
    """Block real import when all required tables are present but the user has not signed.

    Pending per-table entries are allowed during incremental staging, but once
    every required real table is available the registry must carry an explicit
    ``review_status: approved`` plus ``reviewed_by`` and ``reviewed_at``.
    """
    if registry is None or not present_tables:
        return
    required = sorted(REAL_DATA_EXPECTED_TABLES - {"news_event"})
    if not set(required).issubset(present_tables):
        return
    if registry.get("review_status") != "approved":
        raise ValueError(
            "All required real tables are present, but the source registry is not signed. "
            "Set review_status: approved, reviewed_by and reviewed_at after manual review."
        )
    if not str(registry.get("reviewed_by") or "").strip():
        raise ValueError("Source registry reviewed_by is required when all required tables are present")
    if not str(registry.get("reviewed_at") or "").strip():
        raise ValueError("Source registry reviewed_at is required when all required tables are present")


def resolve_financial_revisions(frame: pd.DataFrame) -> pd.DataFrame:
    """Resolve same-announcement duplicates only when revision order is explicit."""
    keys = ["ts_code", "report_period", "ann_date"]
    if not set(keys).issubset(frame.columns) or not frame.duplicated(keys, keep=False).any():
        return frame
    revision_cols = [col for col in ["revision_time", "update_time", "revision_id"] if col in frame]
    if not revision_cols:
        raise ValueError("Duplicate financial announcements require revision_time, update_time, or revision_id")
    return frame.sort_values([*keys, *revision_cols], kind="mergesort").drop_duplicates(keys, keep="last")


def validate_real_financial_revisions(frame: pd.DataFrame) -> None:
    required = {"ts_code", "report_period", "ann_date", "usable_date", "revision_date", "revision_id", "source_id"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Real financial_indicator is missing revision/PIT fields: {missing}")
    key = ["ts_code", "report_period", "ann_date", "revision_id"]
    duplicated = frame.duplicated(key, keep=False)
    if duplicated.any():
        sample = frame.loc[duplicated, key].head(5).to_dict("records")
        raise ValueError(f"Real financial revisions are not unique on {key}. Sample: {sample}")
    ann = pd.to_datetime(frame["ann_date"], errors="coerce")
    revision = pd.to_datetime(frame["revision_date"], errors="coerce")
    usable = pd.to_datetime(frame["usable_date"], errors="coerce")
    latest_information = pd.concat([ann, revision], axis=1).max(axis=1)
    invalid = ann.isna() | revision.isna() | usable.isna() | revision.lt(ann) | usable.le(latest_information)
    if invalid.any():
        raise ValueError("Real financial revisions require revision_date >= ann_date and usable_date after all information dates")


def import_standard_tables(
    source_dir: str | Path,
    output_dir: str | Path,
    mapping_path: str | Path | None = None,
    output_format: str = "parquet",
    mode: str = "sample",
    source_registry_path: str | Path | None = None,
) -> dict[str, Any]:
    """Normalize supplied CSV/Parquet tables and write a versioned manifest."""

    if output_format not in {"csv", "parquet"}:
        raise ValueError("output_format must be csv or parquet")
    if mode not in {"sample", "real"}:
        raise ValueError("mode must be sample or real")
    source = Path(source_dir)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Import output directory is not empty: {output}")
    output = ensure_dir(output)
    mapping = load_yaml(mapping_path) if mapping_path else {}
    present_tables = [
        table for table in STANDARD_TABLES
        if (source / f"{table}.parquet").exists() or (source / f"{table}.csv").exists()
    ]
    registry = None
    registry_validation = None
    if mode == "real":
        if source_registry_path is None:
            raise ValueError("Real import requires --source-registry")
        registry = load_source_registry(source_registry_path)
        registry_validation = validate_source_registry(
            registry,
            present_tables,
            evidence_base=Path(source_registry_path).resolve().parent,
        )
        if not registry_validation.is_valid:
            raise ValueError("; ".join(registry_validation.errors))
        _require_registry_signoff(registry, present_tables)
    missing_required_tables = sorted((REAL_DATA_EXPECTED_TABLES - {"news_event"}) - set(present_tables)) if mode == "real" else []
    manifest: dict[str, Any] = {
        "manifest_version": 2,
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_dir": str(source.resolve()),
        "output_dir": str(output.resolve()),
        "source_registry_path": str(Path(source_registry_path).resolve()) if source_registry_path else None,
        "source_registry_sha256": registry_validation.registry_sha256 if registry_validation else None,
        "source_registry_validation": {
            "valid": registry_validation.is_valid,
            "errors": list(registry_validation.errors),
            "warnings": list(registry_validation.warnings),
        } if registry_validation else {"valid": mode == "sample", "errors": [], "warnings": []},
        "review_status": registry.get("review_status") if registry else None,
        "reviewed_by": registry.get("reviewed_by") if registry else None,
        "reviewed_at": registry.get("reviewed_at") if registry else None,
        "missing_required_tables": missing_required_tables,
        "tables": {},
    }
    for table in STANDARD_TABLES:
        candidates = [source / f"{table}.parquet", source / f"{table}.csv"]
        input_path = next((path for path in candidates if path.exists()), None)
        if input_path is None:
            continue
        frame = _read_source(input_path)
        table_mapping = mapping.get(table, {}) if isinstance(mapping, dict) else {}
        if table_mapping:
            frame = frame.rename(columns=table_mapping)
        frame = normalize_table_dates(frame, table)
        if table == "financial_indicator" and mode == "sample":
            frame = resolve_financial_revisions(frame)
        if table == "financial_indicator" and mode == "real":
            validate_schema(frame, table, check_primary_key=False)
            validate_real_financial_revisions(frame)
        else:
            validate_schema(frame, table, check_primary_key=True)
        sort_cols = [col for col in DATE_COLUMNS.get(table, []) if col in frame]
        if "ts_code" in frame:
            sort_cols.append("ts_code")
        if sort_cols:
            frame = frame.sort_values(sort_cols).reset_index(drop=True)
        output_path = output / f"{table}.{output_format}"
        if output_format == "parquet":
            try:
                frame.to_parquet(output_path, index=False)
            except ImportError as exc:
                raise RuntimeError("Parquet import requires pyarrow.") from exc
        else:
            frame.to_csv(output_path, index=False, encoding="utf-8")
        date_ranges = {}
        for col in DATE_COLUMNS.get(table, []):
            if col in frame and frame[col].notna().any():
                values = pd.to_datetime(frame[col])
                date_ranges[col] = {"min": str(values.min().date()), "max": str(values.max().date())}
        manifest["tables"][table] = {
            "source": str(input_path.resolve()),
            "source_sha256": _sha256(input_path),
            "path": str(output_path.resolve()),
            "output_sha256": _sha256(output_path),
            "content_sha256": dataframe_sha256(frame),
            "rows": int(len(frame)),
            "columns": list(frame.columns),
            "dtypes": {col: str(dtype) for col, dtype in frame.dtypes.items()},
            "date_ranges": date_ranges,
            "source_metadata": sanitized_table_sources(registry, [table]).get(table) if registry else None,
        }
    if not manifest["tables"]:
        raise FileNotFoundError(f"No standard tables found in {source}")
    fingerprint = {
        "schema_version": manifest["schema_version"],
        "tables": {
            name: {
                "rows": metadata["rows"],
                "columns": metadata["columns"],
                "content_sha256": metadata["content_sha256"],
            }
            for name, metadata in sorted(manifest["tables"].items())
        },
    }
    manifest["data_version"] = hashlib.sha256(
        json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    manifest["import_gate_status"] = (
        "ready_for_quality_audit" if not missing_required_tables else "blocked_by_missing_pit_tables"
    )
    manifest["data_gate_status"] = "pending_quality_audit"
    manifest_path = output / "data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
