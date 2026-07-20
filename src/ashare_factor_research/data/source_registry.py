from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ashare_factor_research.utils.io import load_yaml


REQUIRED_SOURCE_FIELDS = {
    "source_type",
    "provider",
    "provider_version",
    "endpoint_or_file",
    "license_status",
    "pit_ready",
    "history_start",
    "units",
    "evidence_path",
}
APPROVED_LICENSE_STATUSES = {"approved_for_research"}


@dataclass(frozen=True)
class SourceRegistryValidation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    registry_sha256: str

    @property
    def is_valid(self) -> bool:
        return not self.errors


def load_source_registry(path: str | Path) -> dict[str, Any]:
    registry = load_yaml(path)
    if not isinstance(registry, dict):
        raise ValueError("Source registry must be a mapping")
    if int(registry.get("schema_version", 0)) != 1:
        raise ValueError("Source registry schema_version must be 1")
    if not isinstance(registry.get("tables"), dict):
        raise ValueError("Source registry must contain a tables mapping")
    return registry


def source_registry_sha256(registry: dict[str, Any]) -> str:
    canonical = json.dumps(registry, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_source_registry(
    registry: dict[str, Any],
    table_names: Iterable[str],
    *,
    required_start: str = "2015-01-01",
    evidence_base: str | Path | None = None,
) -> SourceRegistryValidation:
    errors: list[str] = []
    warnings: list[str] = []
    entries = registry.get("tables", {})
    cutoff = pd.Timestamp(required_start)

    for table in sorted(set(table_names)):
        entry = entries.get(table)
        if not isinstance(entry, dict):
            errors.append(f"{table}: missing source-registry entry")
            continue
        missing = sorted(REQUIRED_SOURCE_FIELDS - set(entry))
        if missing:
            errors.append(f"{table}: missing source fields {missing}")
            continue
        if entry.get("license_status") not in APPROVED_LICENSE_STATUSES:
            errors.append(f"{table}: license_status is not approved_for_research")
        if entry.get("pit_ready") is not True:
            errors.append(f"{table}: pit_ready must be true")
        try:
            history_start = pd.Timestamp(entry.get("history_start"))
        except (TypeError, ValueError):
            errors.append(f"{table}: history_start is invalid")
        else:
            if history_start > cutoff:
                errors.append(f"{table}: history starts after {required_start}")
        if not isinstance(entry.get("units"), dict) or not entry.get("units"):
            errors.append(f"{table}: units must be a non-empty mapping")
        if not str(entry.get("provider_version", "")).strip():
            errors.append(f"{table}: provider_version is required")
        if not str(entry.get("evidence_path", "")).strip():
            errors.append(f"{table}: evidence_path is required")
        elif evidence_base is not None:
            evidence_path = Path(str(entry["evidence_path"]))
            if not evidence_path.is_absolute():
                evidence_path = Path(evidence_base) / evidence_path
            if not evidence_path.exists():
                errors.append(f"{table}: evidence_path does not exist: {evidence_path}")
        if entry.get("source_type") == "open_source" and table in {"stock_basic", "index_member"}:
            warnings.append(f"{table}: open-source current lists require separate historical-survivorship evidence")

    return SourceRegistryValidation(
        errors=tuple(errors),
        warnings=tuple(warnings),
        registry_sha256=source_registry_sha256(registry),
    )


def sanitized_table_sources(registry: dict[str, Any], table_names: Iterable[str]) -> dict[str, Any]:
    entries = registry.get("tables", {})
    return {name: entries[name] for name in sorted(set(table_names)) if name in entries}
