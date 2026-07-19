from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

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
}


def load_research_protocol(path: str | Path) -> dict[str, Any]:
    protocol_path = Path(path).resolve()
    protocol = load_yaml(protocol_path)
    missing = sorted(REQUIRED_PROTOCOL_KEYS - set(protocol))
    if missing:
        raise ValueError(f"Research protocol is missing keys: {missing}")
    if protocol["mode"] not in {"sample", "real"}:
        raise ValueError("protocol mode must be sample or real")
    for key in ("data_dir", "output_root", "project_config", "factor_config", "backtest_config"):
        value = Path(protocol[key])
        if not value.is_absolute():
            value = (protocol_path.parent / value).resolve()
        protocol[key] = str(value)
    canonical = {key: value for key, value in protocol.items() if key != "protocol_sha256"}
    protocol["protocol_sha256"] = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    protocol["protocol_path"] = str(protocol_path)
    return protocol
