"""Versioned TextRepresentationArtifact for the R1 -> R2 boundary."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ashare_factor_research.data.provenance import dataframe_sha256
from ashare_factor_research.llm.schema import validate_llm_event_labels
from ashare_factor_research.llm.text_dataset import validate_prepared_text_events
from ashare_factor_research.llm.text_manifest import (
    assess_text_manifest_research_readiness,
    assert_text_manifest_research_ready,
    text_manifest_sha256,
    validate_text_dataset_manifest,
)
from ashare_factor_research.utils.helpers import require_columns


TEXT_REPRESENTATION_ARTIFACT_TYPE = "r1_text_representation"
TEXT_REPRESENTATION_SCHEMA_VERSION = 1
TEXT_REPRESENTATION_FILENAME = "text_representation.csv"
TEXT_REPRESENTATION_MANIFEST_FILENAME = "text_representation_manifest.json"
REPRESENTATION_TYPES = ("no_text", "rule_labels", "llm_labels", "embedding", "pit_rag")
REPRESENTATION_STATUSES = ("draft", "candidate", "accepted", "rejected", "frozen")
COMMON_REPRESENTATION_COLUMNS = [
    "event_id",
    "stock_code",
    "available_time",
    "raw_text_sha256",
    "dedup_group_id",
    "entity_mapping_status",
    "representation_type",
    "representation_version",
]


def build_label_representation(
    prepared_events: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    representation_type: str = "rule_labels",
    representation_version: str | None = None,
) -> pd.DataFrame:
    """Join labels to PIT metadata without copying raw licensed text."""

    if representation_type not in {"rule_labels", "llm_labels"}:
        raise ValueError("label representation_type must be rule_labels or llm_labels")
    validate_prepared_text_events(prepared_events)
    validate_llm_event_labels(labels)
    if labels["event_id"].duplicated().any():
        raise ValueError("labels event_id must be unique for representation construction")
    metadata_columns = [
        "event_id",
        "stock_code",
        "available_time",
        "raw_text_sha256",
        "dedup_group_id",
        "entity_mapping_status",
    ]
    label_columns = [
        "event_id",
        "stock_code",
        "event_type",
        "sentiment",
        "impact_horizon",
        "confidence",
        "prompt_version",
        "model",
        "cache_key",
    ]
    merged = labels[label_columns].merge(
        prepared_events[metadata_columns],
        on=["event_id", "stock_code"],
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if not merged["_merge"].eq("both").all():
        missing = merged.loc[merged["_merge"].ne("both"), "event_id"].astype(str).tolist()[:5]
        raise ValueError(f"labels reference events missing from the prepared dataset: {missing}")
    merged = merged.drop(columns="_merge")
    versions = sorted(merged["prompt_version"].dropna().astype(str).unique())
    models = sorted(merged["model"].dropna().astype(str).unique())
    if len(versions) > 1 or len(models) > 1:
        raise ValueError("one representation artifact cannot mix prompt or model versions")
    version = representation_version or _configuration_sha256(
        {"type": representation_type, "prompt_version": versions, "model": models}
    )
    merged["representation_type"] = representation_type
    merged["representation_version"] = version
    merged["sentiment_score"] = merged["sentiment"].map(
        {"negative": -1.0, "neutral": 0.0, "positive": 1.0}
    )
    ordered = [
        *COMMON_REPRESENTATION_COLUMNS,
        "event_type",
        "sentiment",
        "sentiment_score",
        "impact_horizon",
        "confidence",
        "prompt_version",
        "model",
        "cache_key",
    ]
    result = merged[ordered].sort_values(["available_time", "event_id"], kind="mergesort").reset_index(drop=True)
    validate_text_representation_rows(result)
    return result


def validate_text_representation_rows(rows: pd.DataFrame) -> None:
    require_columns(rows, COMMON_REPRESENTATION_COLUMNS, "text_representation")
    invalid_types = set(rows["representation_type"].dropna().astype(str)) - set(REPRESENTATION_TYPES)
    if invalid_types:
        raise ValueError(f"invalid representation types: {sorted(invalid_types)}")
    if rows["event_id"].duplicated().any():
        raise ValueError("text representation event_id must be unique")
    if pd.to_datetime(rows["available_time"], errors="coerce").isna().any():
        raise ValueError("text representation available_time must be parseable")
    if not rows["raw_text_sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}").all():
        raise ValueError("text representation raw_text_sha256 is invalid")
    if rows["representation_version"].astype(str).str.strip().eq("").any():
        raise ValueError("representation_version must be non-empty")


def build_text_representation_artifact(
    rows: pd.DataFrame,
    *,
    representation_id: str,
    model_card: dict[str, Any],
    preprocessing: dict[str, Any],
    aggregation: dict[str, Any],
    text_manifest: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    evaluation: dict[str, Any] | None = None,
    trial_id: str | None = None,
    status: str = "draft",
    freeze_ref: str | None = None,
) -> dict[str, Any]:
    validate_text_representation_rows(rows)
    if not isinstance(representation_id, str) or not representation_id.strip():
        raise ValueError("representation_id must be non-empty")
    if status not in REPRESENTATION_STATUSES:
        raise ValueError(f"invalid representation status: {status}")
    representation_types = sorted(rows["representation_type"].dropna().astype(str).unique())
    representation_versions = sorted(rows["representation_version"].dropna().astype(str).unique())
    if len(representation_types) != 1 or len(representation_versions) != 1:
        raise ValueError("artifact rows must contain one representation type and version")
    _validate_model_card(model_card)
    if not preprocessing or not aggregation:
        raise ValueError("preprocessing and aggregation contracts must be non-empty")
    if text_manifest is not None:
        validate_text_dataset_manifest(text_manifest)
        text_manifest_ref = text_manifest_sha256(text_manifest)
        readiness = assess_text_manifest_research_readiness(text_manifest)
    else:
        text_manifest_ref = None
        readiness = {"ready": False, "failures": ["text manifest is missing"]}

    quality_payload = dict(quality or {})
    quality_payload.setdefault("reviewed", False)
    evaluation_payload = dict(evaluation or {})
    evaluation_payload.setdefault("status", "not_run")
    if status in {"accepted", "frozen"}:
        if text_manifest is None:
            raise ValueError("accepted/frozen representation requires a text manifest")
        assert_text_manifest_research_ready(text_manifest)
        if not quality_payload.get("reviewed"):
            raise ValueError("accepted/frozen representation requires reviewed quality evidence")
        if evaluation_payload.get("status") != "accepted":
            raise ValueError("accepted/frozen representation requires an accepted fixed-evaluator result")
    if status == "frozen" and not freeze_ref:
        raise ValueError("frozen representation requires freeze_ref")

    timestamps = pd.to_datetime(rows["available_time"])
    configuration = {
        "representation_id": representation_id,
        "representation_type": representation_types[0],
        "representation_version": representation_versions[0],
        "model_card": model_card,
        "preprocessing": preprocessing,
        "aggregation": aggregation,
        "trial_id": trial_id,
    }
    artifact = {
        "artifact_type": TEXT_REPRESENTATION_ARTIFACT_TYPE,
        "schema_version": TEXT_REPRESENTATION_SCHEMA_VERSION,
        "representation_id": representation_id,
        "status": status,
        "freeze_ref": freeze_ref,
        "trial_id": trial_id,
        "representation_type": representation_types[0],
        "representation_version": representation_versions[0],
        "configuration_sha256": _configuration_sha256(configuration),
        "model_card": dict(model_card),
        "preprocessing": dict(preprocessing),
        "aggregation": dict(aggregation),
        "rows": {
            "count": int(len(rows)),
            "sha256": dataframe_sha256(rows),
            "columns": list(rows.columns),
        },
        "coverage": {
            "unique_stocks": int(rows["stock_code"].nunique()),
            "first_available_time": timestamps.min().isoformat() if len(rows) else None,
            "last_available_time": timestamps.max().isoformat() if len(rows) else None,
            "signal_ready_rows": int(
                rows["entity_mapping_status"].isin(["matched", "reviewed_matched"]).sum()
            ),
        },
        "text_manifest_sha256": text_manifest_ref,
        "text_manifest_readiness": readiness,
        "quality": quality_payload,
        "evaluation": evaluation_payload,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    validate_text_representation_artifact(artifact)
    return artifact


def validate_text_representation_artifact(artifact: dict[str, Any]) -> None:
    if artifact.get("artifact_type") != TEXT_REPRESENTATION_ARTIFACT_TYPE:
        raise ValueError(f"invalid artifact_type: {artifact.get('artifact_type')}")
    if artifact.get("schema_version") != TEXT_REPRESENTATION_SCHEMA_VERSION:
        raise ValueError(f"unsupported representation schema_version: {artifact.get('schema_version')}")
    if artifact.get("status") not in REPRESENTATION_STATUSES:
        raise ValueError(f"invalid representation status: {artifact.get('status')}")
    if artifact.get("representation_type") not in REPRESENTATION_TYPES:
        raise ValueError(f"invalid representation_type: {artifact.get('representation_type')}")
    for key in ("representation_id", "representation_version", "configuration_sha256"):
        if not _has_text(artifact.get(key)):
            raise ValueError(f"representation artifact missing {key}")
    _validate_model_card(artifact.get("model_card", {}))
    if not str(artifact.get("rows", {}).get("sha256", "")):
        raise ValueError("representation artifact rows.sha256 is required")
    if artifact.get("status") == "frozen" and not artifact.get("freeze_ref"):
        raise ValueError("frozen representation requires freeze_ref")


def write_text_representation_artifact(
    rows: pd.DataFrame,
    output_dir: str | Path,
    **artifact_kwargs: Any,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    artifact = build_text_representation_artifact(rows, **artifact_kwargs)
    rows.to_csv(root / TEXT_REPRESENTATION_FILENAME, index=False, encoding="utf-8")
    (root / TEXT_REPRESENTATION_MANIFEST_FILENAME).write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return artifact


def _validate_model_card(model_card: dict[str, Any]) -> None:
    for key in ("model_id", "model_revision", "preprocessing_version", "intended_use", "license_status"):
        if not _has_text(model_card.get(key)):
            raise ValueError(f"model_card.{key} must be non-empty")
    if model_card["license_status"] not in {"approved", "research_only", "internal_only"}:
        raise ValueError(
            "model_card.license_status must be approved, research_only or internal_only"
        )


def _configuration_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
