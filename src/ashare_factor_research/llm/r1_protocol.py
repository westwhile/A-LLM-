"""Frozen-evaluator protocol contract for R1 representation comparisons."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


R1_PROTOCOL_SCHEMA_VERSION = 1
R1_PROTOCOL_STATUSES = ("draft", "frozen", "completed")
REQUIRED_EXPERIMENTS = ("R1-E0", "R1-E1", "R1-E2", "R1-E3")
REQUIRED_METRICS = ("rank_ic", "oos_loss", "coverage")
REQUIRED_NEGATIVE_CONTROLS = ("event_time_shift", "stock_mapping_permutation")


def load_r1_protocol(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("R1 protocol must be a mapping")
    validate_r1_protocol(payload)
    return payload


def validate_r1_protocol(protocol: dict[str, Any]) -> None:
    required = (
        "schema_version",
        "protocol_id",
        "status",
        "research_question",
        "data",
        "split",
        "evaluator",
        "experiments",
        "metrics",
        "negative_controls",
        "trial_budget",
        "stop_rules",
        "human_signoff",
    )
    missing = [key for key in required if key not in protocol]
    if missing:
        raise ValueError(f"R1 protocol missing keys: {missing}")
    if protocol.get("schema_version") != R1_PROTOCOL_SCHEMA_VERSION:
        raise ValueError(f"unsupported R1 protocol schema_version: {protocol.get('schema_version')}")
    if protocol.get("status") not in R1_PROTOCOL_STATUSES:
        raise ValueError(f"invalid R1 protocol status: {protocol.get('status')}")
    if not _has_text(protocol.get("protocol_id")):
        raise ValueError("protocol_id must be non-empty")
    if not _has_text(protocol.get("research_question")):
        raise ValueError("research_question must be non-empty")

    data = _mapping(protocol["data"], "data")
    for key in ("text_manifest_sha256", "structured_feature_manifest_sha256"):
        value = data.get(key)
        if value is not None and not _is_sha256(value):
            raise ValueError(f"data.{key} must be null or a lowercase SHA-256 digest")

    split = _mapping(protocol["split"], "split")
    if int(split.get("minimum_oos_months", 0)) < 36:
        raise ValueError("split.minimum_oos_months must be at least 36")
    if int(split.get("embargo_days", -1)) < 0:
        raise ValueError("split.embargo_days must be non-negative")
    if not isinstance(split.get("final_holdout_accessed"), bool):
        raise ValueError("split.final_holdout_accessed must be a bool")

    evaluator = _mapping(protocol["evaluator"], "evaluator")
    models = evaluator.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("evaluator.models must be a non-empty list")
    model_names: list[str] = []
    for model in models:
        item = _mapping(model, "evaluator.models item")
        name = item.get("name") if _has_text(item.get("name")) else ""
        if not name or not isinstance(item.get("parameters"), dict):
            raise ValueError("each evaluator model needs name and parameters")
        model_names.append(name)
        if protocol["status"] in {"frozen", "completed"} and _contains_search_grid(item["parameters"]):
            raise ValueError(f"frozen evaluator parameters cannot contain search grids: {name}")
    if "linear" not in model_names:
        raise ValueError("R1 evaluator must include the transparent linear baseline")
    if not isinstance(evaluator.get("frozen_during_representation_comparison"), bool):
        raise ValueError("evaluator.frozen_during_representation_comparison must be a bool")

    experiments = protocol["experiments"]
    if not isinstance(experiments, list):
        raise ValueError("experiments must be a list")
    experiment_ids = [str(item.get("experiment_id", "")) for item in experiments if isinstance(item, dict)]
    missing_experiments = [item for item in REQUIRED_EXPERIMENTS if item not in experiment_ids]
    if missing_experiments:
        raise ValueError(f"R1 protocol missing comparison experiments: {missing_experiments}")
    if len(set(experiment_ids)) != len(experiment_ids):
        raise ValueError("R1 experiment_id values must be unique")
    budget = int(protocol["trial_budget"])
    if budget < len(experiments):
        raise ValueError("trial_budget must cover every declared experiment")

    metrics = [str(value) for value in protocol["metrics"]]
    missing_metrics = [value for value in REQUIRED_METRICS if value not in metrics]
    if missing_metrics:
        raise ValueError(f"R1 protocol missing metrics: {missing_metrics}")
    controls = [str(value) for value in protocol["negative_controls"]]
    missing_controls = [value for value in REQUIRED_NEGATIVE_CONTROLS if value not in controls]
    if missing_controls:
        raise ValueError(f"R1 protocol missing negative controls: {missing_controls}")
    if not isinstance(protocol["stop_rules"], list) or not protocol["stop_rules"]:
        raise ValueError("stop_rules must be a non-empty list")

    signoff = _mapping(protocol["human_signoff"], "human_signoff")
    if protocol["status"] in {"frozen", "completed"}:
        for key in ("text_manifest_sha256", "structured_feature_manifest_sha256"):
            if not _is_sha256(data.get(key)):
                raise ValueError(f"frozen/completed R1 protocol requires data.{key}")
        if not _has_text(split.get("final_holdout_start")):
            raise ValueError("frozen/completed R1 protocol requires split.final_holdout_start")
        try:
            datetime.fromisoformat(str(split["final_holdout_start"]))
        except ValueError as exc:
            raise ValueError("split.final_holdout_start must be an ISO date/datetime") from exc
        if protocol["status"] == "frozen" and split["final_holdout_accessed"]:
            raise ValueError("a frozen R1 protocol cannot start after final holdout access")
        if (
            protocol["status"] == "completed"
            and split["final_holdout_accessed"]
            and not _has_text(split.get("final_holdout_access_ref"))
        ):
            raise ValueError("completed R1 protocol requires split.final_holdout_access_ref")
        if not evaluator["frozen_during_representation_comparison"]:
            raise ValueError("frozen R1 protocol requires a frozen evaluator")
        for key in ("approved_by", "approved_at", "approval_ref"):
            if not _has_text(signoff.get(key)):
                raise ValueError(f"frozen R1 protocol requires human_signoff.{key}")


def r1_protocol_sha256(protocol: dict[str, Any]) -> str:
    validate_r1_protocol(protocol)
    payload = {key: value for key, value in protocol.items() if key not in {"created_at", "protocol_sha256"}}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def write_r1_protocol_receipt(protocol: dict[str, Any], output_path: str | Path) -> dict[str, Any]:
    """Write a validation receipt; it never changes or freezes the protocol."""

    digest = r1_protocol_sha256(protocol)
    receipt = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_status": protocol["status"],
        "protocol_sha256": digest,
        "validated": True,
        "research_ready": protocol["status"] in {"frozen", "completed"},
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    Path(output_path).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


def frozen_linear_spec_from_protocol(protocol: dict[str, Any]):
    """Build the executable evaluator spec only after human protocol freeze."""

    validate_r1_protocol(protocol)
    if protocol["status"] not in {"frozen", "completed"}:
        raise ValueError("R1 evaluator execution requires a human-frozen protocol")
    linear_models = [item for item in protocol["evaluator"]["models"] if item.get("name") == "linear"]
    if len(linear_models) != 1:
        raise ValueError("frozen R1 protocol must contain exactly one linear evaluator")
    parameters = linear_models[0]["parameters"]
    split = protocol["split"]
    from ashare_factor_research.llm.evaluator import FrozenLinearEvaluatorSpec

    return FrozenLinearEvaluatorSpec(
        evaluator_id=str(protocol["protocol_id"]) + ":linear",
        train_months=int(split.get("train_months", 24)),
        embargo_days=int(split["embargo_days"]),
        ridge_alpha=float(parameters.get("ridge_alpha", 0.0)),
        min_train_dates=int(split.get("min_train_dates", 6)),
        min_assets_per_test_date=int(split.get("min_assets_per_test_date", 20)),
        standardize=bool(parameters.get("standardize", True)),
        final_holdout_start=split.get("final_holdout_start"),
    )


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _is_sha256(value: Any) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _contains_search_grid(parameters: dict[str, Any]) -> bool:
    for value in parameters.values():
        if isinstance(value, list) and len(value) > 1:
            return True
        if isinstance(value, dict) and _contains_search_grid(value):
            return True
    return False
