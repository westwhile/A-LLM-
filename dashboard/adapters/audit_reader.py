"""统计检验与过拟合审计产物读取（阶段 8，只读）。

覆盖 DM/SPA/DSR/PBO 与试验登记覆盖率：prediction_test_results.csv、
overfit_audit.csv、trial_registry_coverage.csv、promotion_conclusion.csv、
promotion_gate_results.csv。期望列与
``src/ashare_factor_research/time_series/stage8.py`` 的 ``STAGE8_SCHEMAS``
保持一致（实际产物为权威）；列不一致时显式降级并报出期望/实际列。
"""

from __future__ import annotations

from pathlib import Path

from .base import ArtifactResult, read_csv_artifact

#: 阶段 8 审计产物期望列，复制自 stage8.STAGE8_SCHEMAS（time-series-v2，权威）。
AUDIT_SCHEMAS: dict[str, list[str]] = {
    "promotion_gate_results": ["gate", "threshold", "value", "passed", "status", "detail", "model_version"],
    "prediction_test_results": [
        "test", "comparison", "statistic", "p_value", "passed", "fdr_q_value", "fdr_5pct",
        "effective_samples", "status", "model_version",
    ],
    "overfit_audit": [
        "metric", "scope", "statistic", "value", "threshold", "passed", "p_value",
        "fdr_q_value", "fdr_5pct", "trial_count", "effective_samples", "status", "detail", "model_version",
    ],
    "trial_registry_coverage": [
        "module", "registered_trials", "executed_trials", "coverage", "passed",
        "status", "detail", "model_version",
    ],
    "promotion_conclusion": [
        "conclusion", "conclusion_level", "reasons", "dynamic_ready", "data_mode",
        "synthetic_engineering_only", "status", "model_version",
    ],
}

#: 旧版 model_selection_audit.csv（runs/*/figures）的最小期望列。
MODEL_SELECTION_AUDIT_COLUMNS: list[str] = [
    "model", "status", "trial_count", "model_version",
]


def find_stage8_dirs(project_root: Path) -> list[Path]:
    """定位可能包含阶段 8 审计产物的目录：``outputs/stage8*``（只读）。"""
    outputs = Path(project_root) / "outputs"
    if not outputs.is_dir():
        return []
    return sorted(
        path for path in outputs.iterdir()
        if path.is_dir() and path.name.startswith("stage8")
    )


def load_prediction_test_results(audit_dir: Path) -> ArtifactResult:
    """读取 prediction_test_results.csv（DM/SPA 预测检验）。"""
    return read_csv_artifact(
        audit_dir, "prediction_test_results.csv", name="prediction_test_results",
        expected_columns=AUDIT_SCHEMAS["prediction_test_results"],
    )


def load_overfit_audit(audit_dir: Path) -> ArtifactResult:
    """读取 overfit_audit.csv（DSR/PBO 过拟合审计）。"""
    return read_csv_artifact(
        audit_dir, "overfit_audit.csv", name="overfit_audit",
        expected_columns=AUDIT_SCHEMAS["overfit_audit"],
    )


def load_trial_registry_coverage(audit_dir: Path) -> ArtifactResult:
    """读取 trial_registry_coverage.csv（试验登记覆盖率）。"""
    return read_csv_artifact(
        audit_dir, "trial_registry_coverage.csv", name="trial_registry_coverage",
        expected_columns=AUDIT_SCHEMAS["trial_registry_coverage"],
    )


def load_promotion_conclusion(audit_dir: Path) -> ArtifactResult:
    """读取 promotion_conclusion.csv（模型晋级/拒绝结论），透传 synthetic 标记。"""
    result = read_csv_artifact(
        audit_dir, "promotion_conclusion.csv", name="promotion_conclusion",
        expected_columns=AUDIT_SCHEMAS["promotion_conclusion"],
    )
    if result.ok and "synthetic_engineering_only" in result.frame.columns:
        values = {str(v).lower() for v in result.frame["synthetic_engineering_only"].dropna().unique()}
        result.synthetic_engineering_only = bool(values & {"true", "1", "yes"})
    return result


def load_promotion_gate_results(audit_dir: Path) -> ArtifactResult:
    """读取 promotion_gate_results.csv（晋级门槛逐条结果）。"""
    return read_csv_artifact(
        audit_dir, "promotion_gate_results.csv", name="promotion_gate_results",
        expected_columns=AUDIT_SCHEMAS["promotion_gate_results"],
    )


def load_stage8_artifacts(audit_dir: Path) -> dict[str, ArtifactResult]:
    """批量读取阶段 8 审计产物。"""
    return {
        "prediction_test_results": load_prediction_test_results(audit_dir),
        "overfit_audit": load_overfit_audit(audit_dir),
        "trial_registry_coverage": load_trial_registry_coverage(audit_dir),
        "promotion_gate_results": load_promotion_gate_results(audit_dir),
        "promotion_conclusion": load_promotion_conclusion(audit_dir),
    }


def load_model_selection_audit(series_dir: Path) -> ArtifactResult:
    """读取旧版 model_selection_audit.csv（含 DM/SPA/DSR/PBO 列，作为补充证据）。"""
    return read_csv_artifact(
        series_dir, "model_selection_audit.csv", name="model_selection_audit",
        expected_columns=MODEL_SELECTION_AUDIT_COLUMNS,
    )
