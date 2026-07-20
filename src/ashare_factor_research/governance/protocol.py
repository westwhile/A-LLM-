from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ashare_factor_research.utils.io import load_yaml


REQUIRED_PROTOCOL_KEYS = {
    "mode",
    "data_dir",
    "output_root",
    "project_config",
    "factor_config",
    "backtest_config",
    "primary_hypothesis",
    "frozen_after",
    "data_start",
    "evaluation_start",
    "final_holdout_start",
    "frequency",
    "forecast_horizon_months",
    "minimum_oos_months",
    "model_registry",
    "selection",
    "experiment_registry_path",
    "source_registry",
}


def load_research_protocol(path: str | Path) -> dict[str, Any]:
    protocol_path = Path(path).resolve()
    protocol = load_yaml(protocol_path)
    if not isinstance(protocol, dict):
        raise ValueError("Research protocol must be a mapping")
    missing = sorted(REQUIRED_PROTOCOL_KEYS - set(protocol))
    if missing:
        raise ValueError(f"Research protocol is missing keys: {missing}")
    if protocol["mode"] not in {"sample", "real"}:
        raise ValueError("protocol mode must be sample or real")
    dates = [pd.Timestamp(protocol[key]) for key in ("data_start", "evaluation_start", "final_holdout_start")]
    if dates != sorted(dates):
        raise ValueError("Protocol dates must satisfy data_start <= evaluation_start <= final_holdout_start")
    if protocol["frequency"] != "monthly":
        raise ValueError("Protocol frequency must be monthly")
    if int(protocol["forecast_horizon_months"]) != 1:
        raise ValueError("Protocol forecast_horizon_months must be 1")
    if int(protocol["minimum_oos_months"]) < 36:
        raise ValueError("Protocol minimum_oos_months must be at least 36")
    model_registry = protocol["model_registry"]
    if not isinstance(model_registry, dict) or any(
        not isinstance(model_registry.get(name), list) or not model_registry[name]
        for name in ("factor_timing", "regime", "volatility")
    ):
        raise ValueError("Protocol model_registry must define non-empty factor_timing, regime, and volatility lists")
    selection = protocol["selection"]
    if not isinstance(selection, dict):
        raise ValueError("Protocol selection must be a mapping")
    if not {"dm", "spa"}.issubset(set(selection.get("prediction_tests", []))):
        raise ValueError("Protocol prediction_tests must include dm and spa")
    if not {"dsr", "pbo"}.issubset(set(selection.get("overfit_tests", []))):
        raise ValueError("Protocol overfit_tests must include dsr and pbo")
    if protocol["mode"] == "real" and protocol.get("time_series_fallback") != "prohibited":
        raise ValueError("Real protocol must set time_series_fallback to prohibited")

    canonical = {key: value for key, value in protocol.items() if key not in {"protocol_sha256", "protocol_path"}}
    protocol["protocol_sha256"] = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    for key in (
        "data_dir", "output_root", "project_config", "factor_config", "backtest_config",
        "experiment_registry_path", "source_registry",
    ):
        value = Path(protocol[key])
        if not value.is_absolute():
            value = (protocol_path.parent / value).resolve()
        protocol[key] = str(value)
    protocol["protocol_path"] = str(protocol_path)
    return protocol
