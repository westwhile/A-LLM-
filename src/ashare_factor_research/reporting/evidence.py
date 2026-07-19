from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


DEFAULT_CLAIMS = [
    {"claim_id": "engineering_pipeline", "status": "supported", "evidence": ["run_metadata.json", "metrics.csv", "orders.csv", "fills.csv", "positions.csv"]},
    {"claim_id": "pit_timing_explicit", "status": "supported", "evidence": ["figures/factor_panel_timing.csv"]},
    {"claim_id": "factor_real_market_validity", "status": "not_supported_without_real_data", "evidence": ["figures/factor_inference.csv", "figures/walk_forward_oos_ic.csv"]},
    {"claim_id": "execution_constraints", "status": "partially_supported", "evidence": ["figures/execution_compliance.csv", "figures/unfilled_order_analysis.csv"]},
    {"claim_id": "cost_reconciliation", "status": "supported", "evidence": ["figures/cost_attribution.csv", "metrics.csv"]},
    {"claim_id": "time_series_point_in_time", "status": "conditional_on_history", "evidence": ["figures/dynamic_factor_weights.csv", "figures/regime_probabilities.csv", "figures/model_selection_audit.csv", "figures/time_series_report.md"]},
]


def write_evidence_manifest(
    run_dir: str | Path,
    *,
    run_metadata: dict[str, Any],
    claims: list[dict[str, Any]] | None = None,
) -> Path:
    root = Path(run_dir)
    resolved = []
    for claim in claims or DEFAULT_CLAIMS:
        paths = [str(path) for path in claim["evidence"]]
        resolved.append({**claim, "evidence": paths, "all_present": all((root / path).exists() for path in paths)})
    payload = {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_metadata.get("run_id"),
        "git_commit": run_metadata.get("git_commit"),
        "source_tree_sha256": run_metadata.get("source_tree_sha256"),
        "data_version": run_metadata.get("data_version"),
        "protocol_sha256": run_metadata.get("protocol_sha256"),
        "claims": resolved,
    }
    path = root / "evidence_manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
