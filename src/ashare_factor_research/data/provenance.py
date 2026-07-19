from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ashare_factor_research.data.data_loader import LocalDataLoader


SCHEMA_VERSION = 1


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataframe_sha256(frame: pd.DataFrame) -> str:
    canonical = frame.copy()
    canonical = canonical.reindex(sorted(canonical.columns), axis=1)
    for column in canonical.columns:
        if pd.api.types.is_datetime64_any_dtype(canonical[column]):
            canonical[column] = canonical[column].dt.strftime("%Y-%m-%dT%H:%M:%S.%f")
        elif pd.api.types.is_float_dtype(canonical[column]):
            canonical[column] = canonical[column].map(
                # Ten significant digits are stable across CSV parser round-trips
                # while still detecting economically meaningful data changes.
                lambda value: format(float(value), ".10g") if pd.notna(value) else pd.NA
            )
        elif pd.api.types.is_integer_dtype(canonical[column]):
            canonical[column] = canonical[column].astype("Int64").astype("string")
        elif pd.api.types.is_bool_dtype(canonical[column]):
            canonical[column] = canonical[column].astype("boolean").astype("string").str.lower()
        else:
            canonical[column] = canonical[column].astype("string")
    canonical = canonical.fillna("<NA>")
    if len(canonical):
        canonical = canonical.sort_values(list(canonical.columns), kind="mergesort").reset_index(drop=True)
    payload = canonical.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_data_manifest(
    tables: dict[str, pd.DataFrame],
    *,
    mode: str,
    source_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    table_rows = {
        name: {
            "rows": int(len(frame)),
            "columns": list(frame.columns),
            "content_sha256": dataframe_sha256(frame),
        }
        for name, frame in sorted(tables.items())
    }
    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "tables": table_rows,
    }
    data_version = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        **fingerprint_payload,
        "mode": mode,
        "data_version": data_version,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(source_manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if source_manifest
        else None,
    }


def write_data_manifest(
    tables: dict[str, pd.DataFrame],
    output_path: str | Path,
    *,
    mode: str,
    source_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = build_data_manifest(tables, mode=mode, source_manifest=source_manifest)
    Path(output_path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def verify_data_directory(data_dir: str | Path, *, require_manifest: bool = True) -> dict[str, Any]:
    root = Path(data_dir)
    manifest_path = root / "data_manifest.json"
    if require_manifest and not manifest_path.exists():
        raise FileNotFoundError(f"Missing data manifest: {manifest_path}")
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    tables = LocalDataLoader(root, create_if_missing=False).load_all()
    if not tables:
        raise ValueError(f"No standardized tables found in {root}")
    current = build_data_manifest(tables, mode="real" if require_manifest else "sample", source_manifest=source_manifest)
    mismatches: list[str] = []
    if source_manifest:
        for name, metadata in source_manifest.get("tables", {}).items():
            if name not in tables:
                mismatches.append(f"missing table: {name}")
                continue
            expected = metadata.get("content_sha256")
            if expected and expected != dataframe_sha256(tables[name]):
                mismatches.append(f"content hash mismatch: {name}")
            output_path = metadata.get("path")
            output_hash = metadata.get("output_sha256")
            if output_path and output_hash and Path(output_path).exists() and file_sha256(output_path) != output_hash:
                mismatches.append(f"file hash mismatch: {name}")
    if mismatches:
        raise ValueError("; ".join(mismatches))
    return {"verified": True, "tables": len(tables), "mismatches": mismatches, **current}
