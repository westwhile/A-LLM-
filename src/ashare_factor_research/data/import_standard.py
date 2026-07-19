from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ashare_factor_research.data.data_loader import STANDARD_TABLES
from ashare_factor_research.data.provenance import SCHEMA_VERSION, dataframe_sha256
from ashare_factor_research.data.schema import DATE_COLUMNS, normalize_table_dates, validate_schema
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


def resolve_financial_revisions(frame: pd.DataFrame) -> pd.DataFrame:
    """Resolve same-announcement duplicates only when revision order is explicit."""
    keys = ["ts_code", "report_period", "ann_date"]
    if not set(keys).issubset(frame.columns) or not frame.duplicated(keys, keep=False).any():
        return frame
    revision_cols = [col for col in ["revision_time", "update_time", "revision_id"] if col in frame]
    if not revision_cols:
        raise ValueError("Duplicate financial announcements require revision_time, update_time, or revision_id")
    return frame.sort_values([*keys, *revision_cols], kind="mergesort").drop_duplicates(keys, keep="last")


def import_standard_tables(
    source_dir: str | Path,
    output_dir: str | Path,
    mapping_path: str | Path | None = None,
    output_format: str = "parquet",
) -> dict[str, Any]:
    """Normalize supplied CSV/Parquet tables and write a versioned manifest."""

    if output_format not in {"csv", "parquet"}:
        raise ValueError("output_format must be csv or parquet")
    source = Path(source_dir)
    output = ensure_dir(output_dir)
    mapping = load_yaml(mapping_path) if mapping_path else {}
    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_dir": str(source.resolve()),
        "output_dir": str(output.resolve()),
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
        if table == "financial_indicator":
            frame = resolve_financial_revisions(frame)
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
    manifest_path = output / "data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
